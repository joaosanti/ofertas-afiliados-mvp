import os
import posixpath
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

import paramiko


PROJECT_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_HTML_DIR = PROJECT_ROOT / "public_html"
AUTOMATION_DIR = PROJECT_ROOT / "automacao_ofertas"
STORIES_DIR = PUBLIC_HTML_DIR / "stories"


@dataclass(slots=True)
class SftpDeployConfig:
    host: str
    port: int
    username: str
    password: str
    remote_root: str
    stories_public_base_url: str

    @property
    def stories_remote_dir(self) -> str:
        return posixpath.join(self.remote_root, "stories").rstrip("/")

    @property
    def stories_public_url(self) -> str:
        return self.stories_public_base_url.rstrip("/")

    @property
    def automation_remote_dir(self) -> str:
        return posixpath.join(self.remote_root, "automacao_ofertas").rstrip("/")


def _default_site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/")


def _env_port() -> int:
    raw = (os.getenv("SFTP_PORT") or "22").strip() or "22"
    try:
        port = int(raw)
    except ValueError:
        return 22
    return port if port > 0 else 22


def load_sftp_deploy_config() -> SftpDeployConfig:
    host = (os.getenv("SFTP_HOST") or "").strip()
    username = (os.getenv("SFTP_USERNAME") or "").strip()
    password = (os.getenv("SFTP_PASSWORD") or "").strip()
    remote_root = (os.getenv("SFTP_REMOTE_PATH") or "").strip().rstrip("/")
    stories_public_base_url = (os.getenv("STORIES_PUBLIC_BASE_URL") or f"{_default_site_base_url()}/stories").strip()
    port_raw = (os.getenv("SFTP_PORT") or "22").strip() or "22"

    if not host:
        raise ValueError("SFTP_HOST nao preenchido no .env.")
    if not username:
        raise ValueError("SFTP_USERNAME nao preenchido no .env.")
    if not password:
        raise ValueError("SFTP_PASSWORD nao preenchido no .env.")
    if not remote_root:
        raise ValueError("SFTP_REMOTE_PATH nao preenchido no .env.")

    try:
        port = int(port_raw)
    except ValueError as exc:
        raise ValueError("SFTP_PORT precisa ser numerico.") from exc

    if port <= 0:
        raise ValueError("SFTP_PORT precisa ser maior que zero.")

    return SftpDeployConfig(
        host=host,
        port=port,
        username=username,
        password=password,
        remote_root=remote_root,
        stories_public_base_url=stories_public_base_url,
    )


def sftp_settings_snapshot() -> dict[str, Any]:
    enabled = all(
        [
            (os.getenv("SFTP_HOST") or "").strip(),
            (os.getenv("SFTP_USERNAME") or "").strip(),
            (os.getenv("SFTP_PASSWORD") or "").strip(),
            (os.getenv("SFTP_REMOTE_PATH") or "").strip(),
        ]
    )
    return {
        "enabled": enabled,
        "host": (os.getenv("SFTP_HOST") or "").strip(),
        "port": _env_port(),
        "username": (os.getenv("SFTP_USERNAME") or "").strip(),
        "remote_path": (os.getenv("SFTP_REMOTE_PATH") or "").strip(),
        "stories_public_base_url": (os.getenv("STORIES_PUBLIC_BASE_URL") or f"{_default_site_base_url()}/stories").strip(),
    }


def ensure_stories_dir() -> Path:
    STORIES_DIR.mkdir(parents=True, exist_ok=True)
    return STORIES_DIR


def story_public_url(filename: str) -> str:
    config = sftp_settings_snapshot()
    base_url = (config["stories_public_base_url"] or f"{_default_site_base_url()}/stories").rstrip("/")
    return f"{base_url}/{filename}"


def _generated_story_asset_retention_days() -> int:
    raw = (os.getenv("GENERATED_STORY_ASSET_RETENTION_DAYS") or "7").strip() or "7"
    try:
        days = int(raw)
    except ValueError:
        return 7
    return max(0, days)


def _is_generated_story_asset(name: str) -> bool:
    return Path(name).name.lower().startswith("offer-")


def prune_local_generated_story_assets(*, retention_days: int | None = None) -> dict[str, Any]:
    local_dir = ensure_stories_dir()
    normalized_days = _generated_story_asset_retention_days() if retention_days is None else max(0, int(retention_days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=normalized_days)
    removed: list[dict[str, Any]] = []

    for file_path in sorted(local_dir.iterdir()):
        if not file_path.is_file() or not _is_generated_story_asset(file_path.name):
            continue
        modified_at = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        if modified_at > cutoff:
            continue
        size = file_path.stat().st_size
        file_path.unlink(missing_ok=True)
        removed.append(
            {
                "filename": file_path.name,
                "local_path": str(file_path),
                "size": size,
                "modified_at": modified_at.isoformat(),
            }
        )

    return {
        "ok": True,
        "target": "local_stories",
        "retention_days": normalized_days,
        "count": len(removed),
        "items": removed,
    }


def prune_remote_generated_story_assets(
    *,
    retention_days: int | None = None,
    sftp_factory: Callable[[SftpDeployConfig], tuple[Any, Any]] | None = None,
) -> dict[str, Any]:
    config = load_sftp_deploy_config()
    normalized_days = _generated_story_asset_retention_days() if retention_days is None else max(0, int(retention_days))
    cutoff = datetime.now(timezone.utc) - timedelta(days=normalized_days)
    factory = sftp_factory or _connect_sftp
    transport, client = factory(config)
    removed: list[dict[str, Any]] = []
    try:
        _ensure_remote_dir(client, config.stories_remote_dir)
        for entry in client.listdir_attr(config.stories_remote_dir):
            if stat.S_ISDIR(entry.st_mode) or not _is_generated_story_asset(entry.filename):
                continue
            modified_at = datetime.fromtimestamp(int(entry.st_mtime), tz=timezone.utc)
            if modified_at > cutoff:
                continue
            remote_path = posixpath.join(config.stories_remote_dir, entry.filename)
            client.remove(remote_path)
            removed.append(
                {
                    "filename": entry.filename,
                    "remote_path": remote_path,
                    "size": int(entry.st_size),
                    "modified_at": modified_at.isoformat(),
                    "public_url": story_public_url(entry.filename),
                }
            )

        return {
            "ok": True,
            "target": "remote_stories",
            "host": config.host,
            "remote_dir": config.stories_remote_dir,
            "retention_days": normalized_days,
            "count": len(removed),
            "items": removed,
        }
    finally:
        client.close()
        transport.close()


def _connect_sftp(config: SftpDeployConfig) -> tuple[paramiko.Transport, Any]:
    transport = paramiko.Transport((config.host, config.port))
    transport.connect(username=config.username, password=config.password)
    return transport, paramiko.SFTPClient.from_transport(transport)


def _ensure_remote_dir(client: Any, remote_dir: str) -> None:
    current = ""
    for part in [segment for segment in remote_dir.split("/") if segment]:
        current = f"{current}/{part}" if current else f"/{part}"
        try:
            attrs = client.stat(current)
            if not stat.S_ISDIR(attrs.st_mode):
                raise ValueError(f"Caminho remoto nao e diretorio: {current}")
        except FileNotFoundError:
            client.mkdir(current)


def _upload_directory(
    client: Any,
    local_dir: Path,
    remote_dir: str,
    *,
    ignore_prefixes: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    uploaded: list[dict[str, Any]] = []
    base_dir = local_dir.resolve()
    normalized_ignores = tuple(prefix.strip("/").replace("\\", "/") for prefix in ignore_prefixes if prefix)

    for file_path in sorted(base_dir.rglob("*")):
        if not file_path.is_file():
            continue
        relative_path = file_path.relative_to(base_dir).as_posix()
        if normalized_ignores and any(
            relative_path == prefix or relative_path.startswith(f"{prefix}/")
            for prefix in normalized_ignores
        ):
            continue
        target_path = posixpath.join(remote_dir, relative_path)
        target_dir = posixpath.dirname(target_path)
        _ensure_remote_dir(client, target_dir)
        client.put(str(file_path), target_path)
        uploaded.append(
            {
                "relative_path": relative_path,
                "local_path": str(file_path),
                "remote_path": target_path,
                "size": file_path.stat().st_size,
            }
        )

    return uploaded


def deploy_stories_via_sftp(
    *,
    only_files: list[str] | None = None,
    sftp_factory: Callable[[SftpDeployConfig], tuple[Any, Any]] | None = None,
) -> dict[str, Any]:
    config = load_sftp_deploy_config()
    local_dir = ensure_stories_dir()
    if only_files:
        missing = [name for name in only_files if not (local_dir / name).is_file()]
        if missing:
            raise ValueError(f"Arquivos de story nao encontrados: {', '.join(missing)}")

    factory = sftp_factory or _connect_sftp
    transport, client = factory(config)
    try:
        _ensure_remote_dir(client, config.stories_remote_dir)
        if only_files:
            uploaded = []
            for filename in only_files:
                file_path = local_dir / filename
                target_path = posixpath.join(config.stories_remote_dir, filename)
                client.put(str(file_path), target_path)
                uploaded.append(
                    {
                        "relative_path": filename,
                        "local_path": str(file_path),
                        "remote_path": target_path,
                        "size": file_path.stat().st_size,
                        "public_url": story_public_url(filename),
                    }
                )
        else:
            uploaded = _upload_directory(client, local_dir, config.stories_remote_dir)
            for item in uploaded:
                item["public_url"] = story_public_url(item["relative_path"])

        return {
            "ok": True,
            "target": "stories",
            "host": config.host,
            "remote_dir": config.stories_remote_dir,
            "count": len(uploaded),
            "items": uploaded,
        }
    finally:
        client.close()
        transport.close()


def deploy_public_site_via_sftp(
    *,
    sftp_factory: Callable[[SftpDeployConfig], tuple[Any, Any]] | None = None,
) -> dict[str, Any]:
    config = load_sftp_deploy_config()
    if not PUBLIC_HTML_DIR.exists():
        raise ValueError("Diretorio public_html nao encontrado no projeto.")

    factory = sftp_factory or _connect_sftp
    transport, client = factory(config)
    try:
        _ensure_remote_dir(client, config.remote_root)
        uploaded = _upload_directory(client, PUBLIC_HTML_DIR, config.remote_root, ignore_prefixes=("stories",))
        return {
            "ok": True,
            "target": "public_html",
            "host": config.host,
            "remote_dir": config.remote_root,
            "count": len(uploaded),
            "ignored": ["stories"],
            "items": uploaded,
        }
    finally:
        client.close()
        transport.close()


def deploy_automation_backend_via_sftp(
    *,
    sftp_factory: Callable[[SftpDeployConfig], tuple[Any, Any]] | None = None,
) -> dict[str, Any]:
    config = load_sftp_deploy_config()
    if not AUTOMATION_DIR.exists():
        raise ValueError("Diretorio automacao_ofertas nao encontrado no projeto.")

    factory = sftp_factory or _connect_sftp
    transport, client = factory(config)
    try:
        _ensure_remote_dir(client, config.automation_remote_dir)
        uploaded = _upload_directory(
            client,
            AUTOMATION_DIR,
            config.automation_remote_dir,
            ignore_prefixes=(".venv", "__pycache__", "dashboard_ui/node_modules"),
        )
        return {
            "ok": True,
            "target": "automacao_ofertas",
            "host": config.host,
            "remote_dir": config.automation_remote_dir,
            "count": len(uploaded),
            "ignored": [".venv", "__pycache__", "dashboard_ui/node_modules"],
            "items": uploaded,
        }
    finally:
        client.close()
        transport.close()
