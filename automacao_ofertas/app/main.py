import os
import secrets
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import paramiko
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel

from app.collectors.amazon import fetch_amazon_offers
from app.collectors.mercadolivre import fetch_mercadolivre_offers, preview_mercadolivre_offers
from app.collectors.shopee import fetch_shopee_offers, preview_shopee_affiliate_links, preview_shopee_offers
from app.collectors.tiktok import fetch_tiktok_offers
from app.database import SessionLocal
from app.integrations.mercadolivre_oauth import build_auth_url, exchange_code, refresh_token
from app.services.dashboard_data import (
    fetch_dashboard_snapshot,
    record_execution_error,
    record_execution_start,
    record_execution_success,
)
from app.services.category_inference import recategorize_store_offers
from app.services.automation_scheduler import AutomationScheduler
from app.services.manual_file_import import preview_amazon_txt_file, preview_mercadolivre_txt_file, preview_shopee_csv_file
from app.services.manual_link_import import preview_manual_affiliate_links
from app.services.manual_page_import import preview_amazon_saved_html, preview_page_url
from app.services.normalize import build_slug, normalize_offer
from app.services.publish import publish_offer
from app.services.store_maintenance import (
    preview_mercadolivre_existing_offer_relinks,
    relink_mercadolivre_existing_offers,
    repair_amazon_affiliate_links,
    repair_mercadolivre_affiliate_links,
    repair_shopee_affiliate_links,
)
from app.services.sftp_deploy import (
    deploy_public_site_via_sftp,
    deploy_stories_via_sftp,
    sftp_settings_snapshot,
)
from app.services.social_meta import (
    build_meta_post_previews,
    create_instagram_media_container,
    create_instagram_story_container,
    generate_reel_asset,
    generate_story_asset,
    publish_facebook_offer_batch,
    publish_facebook_post,
    publish_facebook_reel,
    publish_instagram_container,
)

app = FastAPI(title="Automacao de Ofertas")
UI_DIR = Path(__file__).resolve().parents[1] / "dashboard_ui"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
scheduler: AutomationScheduler | None = None


def _database_error_message(exc: Exception) -> str:
    raw_url = (os.getenv("DATABASE_URL") or "").strip()
    if not raw_url:
        return "DATABASE_URL nao configurada."

    parsed = urlsplit(raw_url)
    host = parsed.hostname or "host-desconhecido"
    port = parsed.port or 3306
    username = parsed.username or "usuario-desconhecido"
    detail = str(getattr(exc, "orig", exc))
    return (
        "Falha ao conectar no banco de dados. "
        f"Verifique usuario/senha e permissao do host para '{username}' em {host}:{port}. "
        f"Detalhe original: {detail}"
    )


def _empty_dashboard_snapshot(error_message: str) -> dict[str, Any]:
    return {
        "overview": {
            "active_offers": 0,
            "featured_offers": 0,
            "tracked_stores": 0,
            "clicks_7d": 0,
            "clicks_30d": 0,
            "average_price": 0,
            "import_runs_7d": 0,
            "social_posts_7d": 0,
        },
        "charts": {
            "clicks_by_day": [],
            "offers_by_store": [],
            "offers_by_category": [],
            "runs_by_day": [],
        },
        "tables": {
            "top_clicked": [],
            "recent_offers": [],
            "recent_runs": [],
        },
        "providers": {"imports": [], "social": []},
        "database": {"ok": False, "error": error_message},
    }


class MeliCodePayload(BaseModel):
    code: str


class MeliRefreshPayload(BaseModel):
    refresh_token: str


class MetaFacebookPostPayload(BaseModel):
    message: str
    link: str | None = None


class MetaFacebookBatchPayload(BaseModel):
    limit: int = 5
    offer_ids: list[int] | None = None


class MetaInstagramCreatePayload(BaseModel):
    image_url: str
    caption: str


class MetaInstagramPublishPayload(BaseModel):
    creation_id: str


class MetaStoryPayload(BaseModel):
    offer_id: int | None = None
    limit: int = 1


class MetaInstagramStoryCreatePayload(BaseModel):
    image_url: str


class DashboardImportRunPayload(BaseModel):
    providers: list[str] | None = None


class DashboardShopeeLinksPayload(BaseModel):
    links: list[str]


class DashboardManualLinkItemPayload(BaseModel):
    provider: str
    store: str | None = None
    title: str
    description: str | None = None
    price: float | int | str = 0
    old_price: float | int | str | None = None
    url: str
    canonical_url: str | None = None
    image: str | None = None
    category: str | None = None
    coupon: str | None = None
    tags: str | None = None
    featured: int | None = None
    affiliate_detected: bool | None = None
    affiliate_code: str | None = None
    affiliate_status: str | None = None
    affiliate_warning: str | None = None
    import_allowed: bool | None = None
    item_id: str | None = None
    product_id: str | None = None


class DashboardManualLinksPayload(BaseModel):
    links: list[str] | None = None
    items: list[DashboardManualLinkItemPayload] | None = None


class DashboardMercadoLivreRelinkItemPayload(BaseModel):
    url: str
    canonical_url: str | None = None
    title: str | None = None
    affiliate_detected: bool | None = None
    matched_offer_id: int | None = None
    matched_offer_active: int | None = None
    selected: bool = True


class DashboardMercadoLivreRelinkPayload(BaseModel):
    links: list[str] | None = None
    items: list[DashboardMercadoLivreRelinkItemPayload] | None = None


class DashboardManualPagePayload(BaseModel):
    provider: str | None = None
    url: str
    limit: int = 10


class DashboardSocialRunPayload(BaseModel):
    platform: str
    mode: str = "feed"
    limit: int = 1
    offer_ids: list[int] | None = None


class DashboardSettingsPayload(BaseModel):
    manager_username: str | None = None
    manager_password: str | None = None
    meta_access_token: str | None = None
    auto_import_enabled: bool | None = None
    auto_import_times: str | None = None
    auto_import_providers: list[str] | None = None
    auto_social_enabled: bool | None = None
    auto_social_times: str | None = None
    auto_social_platform: str | None = None
    auto_social_mode: str | None = None
    auto_social_limit: int | None = None
    auto_story_enabled: bool | None = None
    auto_story_times: str | None = None
    auto_story_platform: str | None = None
    auto_story_limit: int | None = None
    sftp_host: str | None = None
    sftp_port: int | None = None
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_remote_path: str | None = None
    stories_public_base_url: str | None = None


class DashboardStoreRecategorizePayload(BaseModel):
    store: str = "Shopee"
    only_uncategorized: bool = True


class DashboardAmazonRepairPayload(BaseModel):
    only_inactive: bool = True


class DashboardJobRunPayload(BaseModel):
    providers: list[str] | None = None
    platform: str | None = None
    mode: str | None = None
    limit: int | None = None


class DashboardDeployPayload(BaseModel):
    only_files: list[str] | None = None


class DashboardOfferUpdatePayload(BaseModel):
    titulo: str
    slug: str | None = None
    descricao: str | None = None
    preco: float | int | str = 0
    preco_antigo: float | int | str | None = None
    loja: str | None = None
    url_afiliado: str
    cupom: str | None = None
    imagem_url: str | None = None
    categoria: str | None = None
    tags: str | None = None
    destaque: bool = False
    ativo: bool = True
    expira_em: str | None = None


def _bool_env(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "sim"}


def _site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/")


def _parse_decimal(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    raw = str(value).strip()
    if not raw:
        return default
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return default


def _normalize_offer_slug(db, slug: str | None, title: str, ignore_id: int = 0) -> str:
    base = build_slug((slug or "").strip() or title)
    candidate = base
    suffix = 2
    while True:
        params = {"slug": candidate}
        sql = "SELECT id FROM ofertas WHERE slug = :slug"
        if ignore_id > 0:
            sql += " AND id <> :ignore_id"
            params["ignore_id"] = ignore_id
        sql += " LIMIT 1"
        exists = db.execute(text(sql), params).scalar()
        if not exists:
            return candidate
        suffix_text = f"-{suffix}"
        candidate = f"{base[: max(1, 170 - len(suffix_text))]}{suffix_text}"
        suffix += 1


def _manager_auth_enabled() -> bool:
    return _bool_env("MANAGER_AUTH_ENABLED", True)


def _manager_credentials() -> tuple[str, str]:
    return (
        (os.getenv("MANAGER_USERNAME") or "admin").strip() or "admin",
        (os.getenv("MANAGER_PASSWORD") or "zeropreco123").strip() or "zeropreco123",
    )


def _manager_cookie_name() -> str:
    return "zp_manager_session"


def _manager_session_value() -> str:
    username, password = _manager_credentials()
    seed = f"{username}:{password}:{os.getenv('META_APP_ID', 'zeropreco')}"
    return sha256(seed.encode("utf-8")).hexdigest()


def _manager_login_html(error: str | None = None) -> str:
    message = f"<p class='login-error'>{error}</p>" if error else ""
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Zero Preco Manager Login</title>
  <style>
    :root {{
      --bg:#071a45; --panel:#ffffff; --accent:#1d63ff; --text:#0e214f; --muted:#667494; --danger:#b63131;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0; min-height:100vh; display:grid; place-items:center;
      background:
        radial-gradient(circle at 20% 20%, rgba(45,108,255,.28), transparent 32%),
        radial-gradient(circle at 80% 15%, rgba(32,173,116,.16), transparent 28%),
        linear-gradient(160deg,#061534,#0e2a68 55%,#123078);
      font-family: "Segoe UI", Arial, sans-serif; color:var(--text);
    }}
    .card {{
      width:min(460px, calc(100vw - 32px)); background:rgba(255,255,255,.96);
      border:1px solid rgba(10,31,75,.08); border-radius:28px; padding:32px;
      box-shadow:0 24px 70px rgba(4,17,46,.28);
    }}
    .brand {{ display:flex; gap:14px; align-items:center; margin-bottom:20px; }}
    .mark {{
      width:54px; height:54px; border-radius:16px; display:grid; place-items:center;
      background:linear-gradient(135deg,#1d63ff,#0b2d78); color:#fff; font-weight:800;
    }}
    h1 {{ margin:0; font-size:1.6rem; }}
    p {{ margin:6px 0 0; color:var(--muted); }}
    form {{ display:grid; gap:14px; margin-top:24px; }}
    label {{ display:grid; gap:8px; font-size:.95rem; color:var(--text); font-weight:600; }}
    input {{
      width:100%; border-radius:16px; border:1px solid rgba(13,35,79,.12); padding:14px 16px; font-size:1rem;
    }}
    button {{
      border:none; border-radius:16px; padding:14px 16px; font-size:1rem; font-weight:700;
      background:linear-gradient(135deg,#1d63ff,#0b2d78); color:#fff; cursor:pointer;
    }}
    .helper {{ margin-top:16px; font-size:.9rem; color:var(--muted); }}
    .login-error {{ margin-top:10px; color:var(--danger); font-weight:700; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="brand">
      <div class="mark">ZP</div>
      <div>
        <h1>Zero Preco Manager</h1>
        <p>Entrar no painel de importacao, social e analytics.</p>
      </div>
    </div>
    {message}
    <form method="post" action="/manager/login">
      <label>Usuario
        <input name="username" autocomplete="username" required />
      </label>
      <label>Senha
        <input name="password" type="password" autocomplete="current-password" required />
      </label>
      <button type="submit">Entrar</button>
    </form>
    <div class="helper">O painel agora usa sessao propria. Se preferir, troque as credenciais no .env.</div>
  </div>
</body>
</html>"""


def _env_settings_snapshot() -> dict:
    return {
        "manager_username": _manager_credentials()[0],
        "meta_access_token_configured": bool((os.getenv("META_ACCESS_TOKEN") or "").strip()),
        "auto_import_enabled": _bool_env("AUTO_IMPORT_ENABLED", False),
        "auto_import_times": os.getenv("AUTO_IMPORT_TIMES") or "",
        "auto_import_providers": [item.strip() for item in (os.getenv("AUTO_IMPORT_PROVIDERS") or "mercadolivre").split(",") if item.strip()],
        "auto_social_enabled": _bool_env("AUTO_SOCIAL_ENABLED", False),
        "auto_social_times": os.getenv("AUTO_SOCIAL_TIMES") or "",
        "auto_social_platform": (os.getenv("AUTO_SOCIAL_PLATFORM") or "facebook").strip().lower(),
        "auto_social_mode": (os.getenv("AUTO_SOCIAL_MODE") or "feed").strip().lower(),
        "auto_social_limit": max(1, int((os.getenv("AUTO_SOCIAL_LIMIT") or "3").strip() or "3")),
        "auto_story_enabled": _bool_env("AUTO_STORY_ENABLED", False),
        "auto_story_times": os.getenv("AUTO_STORY_TIMES") or "",
        "auto_story_platform": (os.getenv("AUTO_STORY_PLATFORM") or "instagram").strip().lower(),
        "auto_story_limit": max(1, int((os.getenv("AUTO_STORY_LIMIT") or "1").strip() or "1")),
        "sftp": sftp_settings_snapshot(),
    }


def _write_env_updates(updates: dict[str, str]) -> None:
    if not ENV_FILE.exists():
        raise HTTPException(status_code=500, detail=".env nao encontrado.")

    content = ENV_FILE.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    output: list[str] = []

    for line in content:
        replaced = False
        for key, value in list(remaining.items()):
            prefix = f"{key}="
            if line.startswith(prefix):
                output.append(f"{key}={value}")
                remaining.pop(key, None)
                replaced = True
                break
        if not replaced:
            output.append(line)

    for key, value in remaining.items():
        output.append(f"{key}={value}")

    ENV_FILE.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")

    for key, value in updates.items():
        os.environ[key] = value


def require_manager_auth(manager_session: str | None = Cookie(default=None, alias="zp_manager_session")) -> str:
    if not _manager_auth_enabled():
        return "disabled"
    if manager_session and secrets.compare_digest(manager_session, _manager_session_value()):
        return "ok"
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Sessao invalida.")


def _import_provider(db, store: str, offers: list[dict]) -> dict:
    processed = 0
    created = 0
    updated = 0
    for raw in offers:
        normalized = normalize_offer(raw, store, raw.get("affiliate_tag"))
        action = publish_offer(db, normalized)
        processed += 1
        if action == "created":
            created += 1
        else:
            updated += 1
    return {"processed": processed, "created": created, "updated": updated}


def _raise_meta_http_error(exc: httpx.HTTPStatusError) -> HTTPException:
    detail = exc.response.text if exc.response is not None else str(exc)
    status_code = exc.response.status_code if exc.response is not None else 502
    lowered = detail.lower()
    if "session has expired" in lowered or "\"code\":190" in lowered or "\"error_subcode\":463" in lowered:
        detail = (
            "Token da Meta expirou. Gere um novo META_ACCESS_TOKEN no Graph API Explorer "
            "e atualize o .env antes de rodar a publicacao social."
        )
    return HTTPException(status_code=status_code, detail=detail)


def _normalize_provider_key(value: str) -> str:
    raw = (value or "").strip().lower()
    mapping = {
        "mercado livre": "mercadolivre",
        "mercadolivre": "mercadolivre",
        "meli": "mercadolivre",
        "shopee": "shopee",
        "amazon": "amazon",
        "tiktok": "tiktok",
        "tiktok shop": "tiktok",
    }
    return mapping.get(raw, raw)


def _provider_label(key: str) -> str:
    mapping = {
        "mercadolivre": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "tiktok": "TikTok",
    }
    return mapping[key]


def _provider_fetcher(key: str):
    mapping = {
        "mercadolivre": fetch_mercadolivre_offers,
        "shopee": fetch_shopee_offers,
        "amazon": fetch_amazon_offers,
        "tiktok": fetch_tiktok_offers,
    }
    if key not in mapping:
        raise ValueError(f"Provedor nao suportado: {key}")
    return mapping[key]


def execute_import_run(providers: list[str] | None = None) -> dict:
    db = SessionLocal()
    items = providers or ["mercadolivre", "shopee", "amazon", "tiktok"]
    results = []

    try:
        for item in items:
            provider_key = _normalize_provider_key(item)
            run_id = record_execution_start(
                db,
                tipo="import",
                provider=provider_key,
                requested_count=0,
                payload={"provider": provider_key},
            )

            try:
                fetcher = _provider_fetcher(provider_key)
                offers = fetcher()
                import_summary = _import_provider(db, _provider_label(provider_key), offers)
                db.commit()
                result = {
                    "provider": provider_key,
                    "processed": import_summary["processed"],
                    "created": import_summary["created"],
                    "updated": import_summary["updated"],
                    "imported": import_summary["processed"],
                    "offers_found": len(offers),
                }
                record_execution_success(db, run_id, processed_count=import_summary["processed"], result=result)
                results.append({"run_id": run_id, "status": "success"} | result)
            except Exception as exc:  # noqa: BLE001
                db.rollback()
                error_message = str(exc)
                record_execution_error(db, run_id, error_message=error_message)
                results.append(
                    {
                        "run_id": run_id,
                        "provider": provider_key,
                        "status": "error",
                        "error": error_message,
                    }
                )

        return {
            "ok": True,
            "count": len(results),
            "success": len([item for item in results if item["status"] == "success"]),
            "error": len([item for item in results if item["status"] == "error"]),
            "items": results,
        }
    finally:
        db.close()


def execute_social_run(platform: str, mode: str = "feed", limit: int = 1, offer_ids: list[int] | None = None) -> dict:
    platform = (platform or "").strip().lower()
    mode = (mode or "feed").strip().lower()
    limit = max(1, min(limit, 20))
    selected_offer_ids = [int(item) for item in (offer_ids or []) if str(item).strip()]
    if selected_offer_ids:
        limit = min(limit, len(selected_offer_ids))
    db = SessionLocal()

    run_id = record_execution_start(
        db,
        tipo="social",
        canal=platform,
        modo=mode,
        requested_count=limit,
        payload={"platform": platform, "mode": mode, "limit": limit, "offer_ids": selected_offer_ids},
    )

    try:
        if platform == "facebook" and mode == "feed":
            result = publish_facebook_offer_batch(db, limit=limit, offer_ids=selected_offer_ids or None)
            record_execution_success(db, run_id, processed_count=int(result["count"]), result=result)
            return {"run_id": run_id} | result

        previews = build_meta_post_previews(
            db,
            limit=limit,
            offer_ids=selected_offer_ids or None,
            include_story_assets=((platform == "instagram" and mode in {"story", "feed_story"}) or (platform in {"both", "facebook_instagram"} and mode == "feed_story")),
        )
        if not previews:
            raise ValueError("Nao ha ofertas elegiveis para publicar.")

        items = []
        errors = []
        if platform in {"both", "facebook_instagram"} and mode == "feed":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    facebook_result = publish_facebook_post(
                        message=item["facebook_payload"]["message"],
                        link=item["facebook_payload"]["link"],
                    )
                    combined_item["facebook_result"] = facebook_result["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook",
                            "error": str(exc),
                        }
                    )

                try:
                    created = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published = publish_instagram_container(created["result"]["id"])
                    combined_item["instagram_creation_id"] = created["result"]["id"]
                    combined_item["instagram_result"] = published["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram",
                            "error": str(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        elif platform in {"both", "facebook_instagram"} and mode == "feed_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    facebook_result = publish_facebook_post(
                        message=item["facebook_payload"]["message"],
                        link=item["facebook_payload"]["link"],
                    )
                    combined_item["facebook_result"] = facebook_result["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook",
                            "error": str(exc),
                        }
                    )

                try:
                    created_feed = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published_feed = publish_instagram_container(created_feed["result"]["id"])
                    combined_item["feed_creation_id"] = created_feed["result"]["id"]
                    combined_item["feed_result"] = published_feed["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_feed",
                            "error": str(exc),
                        }
                    )

                try:
                    story_filename = item["story_payload"]["image_url"].rstrip("/").split("/")[-1]
                    deploy_result = deploy_stories_via_sftp(only_files=[story_filename])
                    created_story = create_instagram_story_container(item["story_payload"]["image_url"])
                    published_story = publish_instagram_container(created_story["result"]["id"])
                    combined_item["story_deploy"] = deploy_result
                    combined_item["story_creation_id"] = created_story["result"]["id"]
                    combined_item["story_result"] = published_story["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": str(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        elif platform == "facebook" and mode == "reel":
            for item in previews:
                try:
                    offer = {
                        "id": item["offer_id"],
                        "slug": item["slug"],
                        "titulo": item["title"],
                        "preco": item["price"],
                        "preco_antigo": item.get("old_price"),
                        "loja": item["store"],
                        "categoria": item["category"],
                        "imagem_url": item["image_url"],
                        "url_afiliado": item.get("cta_url"),
                        "cupom": item.get("coupon"),
                    }
                    reel_asset = generate_reel_asset(offer)
                    published = publish_facebook_reel(
                        video_path=reel_asset["file_path"],
                        description=item["reel_payload"]["caption"],
                    )
                    items.append(
                        {
                            "offer_id": item["offer_id"],
                            "slug": item["slug"],
                            "title": item["title"],
                            "reel_file": reel_asset["filename"],
                            "video_id": published["video_id"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": str(exc)})
        elif platform == "instagram" and mode == "feed":
            for item in previews:
                try:
                    created = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published = publish_instagram_container(created["result"]["id"])
                    items.append(
                        {
                            "offer_id": item["offer_id"],
                            "slug": item["slug"],
                            "title": item["title"],
                            "creation_id": created["result"]["id"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": str(exc)})
        elif platform == "instagram" and mode == "story":
            for item in previews:
                try:
                    story_filename = item["story_payload"]["image_url"].rstrip("/").split("/")[-1]
                    deploy_result = deploy_stories_via_sftp(only_files=[story_filename])
                    created = create_instagram_story_container(item["story_payload"]["image_url"])
                    published = publish_instagram_container(created["result"]["id"])
                    items.append(
                        {
                            "offer_id": item["offer_id"],
                            "slug": item["slug"],
                            "title": item["title"],
                            "story_deploy": deploy_result,
                            "creation_id": created["result"]["id"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": str(exc)})
        elif platform == "instagram" and mode == "feed_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    created_feed = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published_feed = publish_instagram_container(created_feed["result"]["id"])
                    combined_item["feed_creation_id"] = created_feed["result"]["id"]
                    combined_item["feed_result"] = published_feed["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_feed",
                            "error": str(exc),
                        }
                    )

                try:
                    story_filename = item["story_payload"]["image_url"].rstrip("/").split("/")[-1]
                    deploy_result = deploy_stories_via_sftp(only_files=[story_filename])
                    created_story = create_instagram_story_container(item["story_payload"]["image_url"])
                    published_story = publish_instagram_container(created_story["result"]["id"])
                    combined_item["story_deploy"] = deploy_result
                    combined_item["story_creation_id"] = created_story["result"]["id"]
                    combined_item["story_result"] = published_story["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": str(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        else:
            raise HTTPException(status_code=400, detail=f"Acao social nao suportada: {platform}/{mode}")

        result = {
            "ok": len(items) > 0,
            "platform": platform,
            "mode": mode,
            "count": len(items),
            "facebook_count": len([item for item in items if item.get("facebook_result")]),
            "instagram_count": len(
                [
                    item
                    for item in items
                    if item.get("instagram_result")
                    or item.get("creation_id")
                    or item.get("feed_result")
                    or item.get("story_result")
                ]
            ),
            "instagram_feed_count": len([item for item in items if item.get("feed_result")]),
            "instagram_story_count": len([item for item in items if item.get("story_result") or item.get("story_deploy")]),
            "facebook_reel_count": len([item for item in items if item.get("video_id")]),
            "items": items,
            "errors": errors,
            "error_summary": (errors[0].get("error") if errors else ""),
        }
        if items:
            record_execution_success(db, run_id, processed_count=len(items), result=result)
        else:
            record_execution_error(db, run_id, error_message="Nenhuma publicacao concluida.", result=result)
        return {"run_id": run_id} | result
    except HTTPException:
        raise
    except ValueError as e:
        record_execution_error(db, run_id, error_message=str(e))
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        record_execution_error(db, run_id, error_message=e.response.text if e.response is not None else str(e))
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        record_execution_error(db, run_id, error_message=str(e))
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        db.close()


def execute_deploy_stories(only_files: list[str] | None = None) -> dict:
    db = SessionLocal()
    run_id = record_execution_start(
        db,
        tipo="deploy",
        canal="sftp",
        modo="stories",
        requested_count=len(only_files or []),
        payload={"target": "stories", "only_files": only_files or []},
    )
    try:
        result = deploy_stories_via_sftp(only_files=only_files)
        record_execution_success(db, run_id, processed_count=int(result.get("count") or 0), result=result)
        return {"run_id": run_id} | result
    except Exception as exc:  # noqa: BLE001
        record_execution_error(db, run_id, error_message=str(exc))
        raise
    finally:
        db.close()


def execute_deploy_site() -> dict:
    db = SessionLocal()
    run_id = record_execution_start(
        db,
        tipo="deploy",
        canal="sftp",
        modo="public_html",
        requested_count=0,
        payload={"target": "public_html"},
    )
    try:
        result = deploy_public_site_via_sftp()
        record_execution_success(db, run_id, processed_count=int(result.get("count") or 0), result=result)
        return {"run_id": run_id} | result
    except Exception as exc:  # noqa: BLE001
        record_execution_error(db, run_id, error_message=str(exc))
        raise
    finally:
        db.close()


@app.on_event("startup")
def startup_scheduler():
    global scheduler
    scheduler = AutomationScheduler(
        import_runner=execute_import_run,
        social_runner=execute_social_run,
    )
    scheduler.start()


@app.on_event("shutdown")
def shutdown_scheduler():
    if scheduler is not None:
        scheduler.stop()


@app.get("/")
def root():
    return {
        "name": "Automacao de Ofertas",
        "status": "ok",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/manager", response_class=HTMLResponse)
def manager_ui(request: Request, manager_session: str | None = Cookie(default=None, alias="zp_manager_session")):
    if _manager_auth_enabled() and (not manager_session or not secrets.compare_digest(manager_session, _manager_session_value())):
        return RedirectResponse(url="/manager/login", status_code=303)
    index_path = UI_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard React ainda nao foi gerado.")
    return index_path.read_text(encoding="utf-8")


@app.get("/manager/login", response_class=HTMLResponse)
def manager_login_page():
    if not _manager_auth_enabled():
        return RedirectResponse(url="/manager", status_code=303)
    return _manager_login_html()


@app.post("/manager/login")
def manager_login_submit(username: str = Form(...), password: str = Form(...)):
    expected_user, expected_password = _manager_credentials()
    valid_user = secrets.compare_digest(username or "", expected_user)
    valid_password = secrets.compare_digest(password or "", expected_password)
    if not (valid_user and valid_password):
        return HTMLResponse(_manager_login_html("Usuario ou senha invalidos."), status_code=401)

    response = RedirectResponse(url="/manager", status_code=303)
    response.set_cookie(
        key=_manager_cookie_name(),
        value=_manager_session_value(),
        httponly=True,
        samesite="lax",
        secure=False,
        max_age=60 * 60 * 12,
    )
    return response


@app.post("/manager/logout")
def manager_logout():
    response = RedirectResponse(url="/manager/login", status_code=303)
    response.delete_cookie(_manager_cookie_name())
    return response


@app.get("/favicon.ico")
def dashboard_favicon():
    favicon_path = UI_DIR / "logo-zp.png"
    if not favicon_path.exists():
        raise HTTPException(status_code=404, detail="Favicon nao encontrado.")
    return FileResponse(favicon_path)


@app.get("/manager-assets/{asset_path:path}")
def manager_ui_assets(asset_path: str, _: str = Depends(require_manager_auth)):
    asset = (UI_DIR / asset_path).resolve()
    try:
        asset.relative_to(UI_DIR.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Asset invalido.") from exc

    if not asset.exists() or not asset.is_file():
        raise HTTPException(status_code=404, detail="Asset nao encontrado.")

    return FileResponse(asset)


@app.get("/dashboard/api/overview")
def dashboard_api_overview(_: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        try:
            snapshot = fetch_dashboard_snapshot(db)
        except OperationalError as exc:
            snapshot = _empty_dashboard_snapshot(_database_error_message(exc))
        snapshot["site_base_url"] = _site_base_url()
        snapshot["automation"] = scheduler.snapshot() if scheduler is not None else None
        snapshot["manager"] = {
            "auth_enabled": _manager_auth_enabled(),
            "username": _manager_credentials()[0],
        }
        snapshot["settings"] = _env_settings_snapshot()
        return snapshot
    finally:
        db.close()


@app.get("/dashboard/api/import/preview")
def dashboard_api_import_preview(provider: str, keyword: str, limit: int = 10, pages: int = 1, _: str = Depends(require_manager_auth)):
    provider_key = _normalize_provider_key(provider)
    try:
        if provider_key == "mercadolivre":
            items = preview_mercadolivre_offers(keyword=keyword, limit=limit, pages=pages)
        elif provider_key == "shopee":
            items = preview_shopee_offers(keyword=keyword, limit=limit, pages=pages)
        else:
            raise HTTPException(status_code=501, detail=f"Preview ainda nao implementado para {provider}.")
        return {"provider": provider_key, "keyword": keyword, "count": len(items), "items": items}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/api/import/run")
def dashboard_api_import_run(payload: DashboardImportRunPayload, _: str = Depends(require_manager_auth)):
    return execute_import_run(payload.providers)


@app.post("/dashboard/api/import/shopee-links/preview")
def dashboard_api_shopee_links_preview(payload: DashboardShopeeLinksPayload, _: str = Depends(require_manager_auth)):
    try:
        items = preview_shopee_affiliate_links(payload.links)
        return {"provider": "shopee_manual", "count": len(items), "items": items}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/dashboard/api/import/shopee-links/run")
def dashboard_api_shopee_links_run(payload: DashboardShopeeLinksPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        offers = preview_shopee_affiliate_links(payload.links)
        summary = _import_provider(db, "Shopee", offers)
        db.commit()
        return {
            "ok": True,
            "provider": "shopee_manual",
            "count": len(offers),
            "processed": summary["processed"],
            "created": summary["created"],
            "updated": summary["updated"],
            "items": [
                {
                    "title": item.get("title"),
                    "price": float(item.get("price") or 0),
                    "url": item.get("url"),
                    "image": item.get("image"),
                    "category": item.get("category"),
                }
                for item in offers
            ],
        }
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        db.rollback()
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        db.rollback()
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/import/manual-links/preview")
def dashboard_api_manual_links_preview(payload: DashboardManualLinksPayload, _: str = Depends(require_manager_auth)):
    try:
        items = preview_manual_affiliate_links(payload.links or [])
        return {"provider": "manual_links", "count": len(items), "items": items}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/api/import/store/mercadolivre/relink-existing/preview")
def dashboard_api_mercadolivre_relink_existing_preview(payload: DashboardMercadoLivreRelinkPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        items = preview_mercadolivre_existing_offer_relinks(db, payload.links or [])
        return {"provider": "mercadolivre_relink", "count": len(items), "items": items}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        db.close()


@app.get("/dashboard/api/offers")
def dashboard_api_offers(q: str = "", limit: int = 12, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        normalized_limit = min(max(int(limit or 12), 1), 50)
        query = (q or "").strip()
        params: dict[str, Any] = {"limit": normalized_limit}
        sql = """
            SELECT
              id,
              slug,
              titulo,
              descricao,
              preco,
              preco_antigo,
              loja,
              url_afiliado,
              cupom,
              imagem_url,
              categoria,
              tags,
              destaque,
              ativo,
              expira_em,
              atualizado_em
            FROM ofertas
        """
        if query:
            sql += """
            WHERE titulo LIKE :query
               OR slug LIKE :query
               OR loja LIKE :query
               OR categoria LIKE :query
               OR tags LIKE :query
            """
            params["query"] = f"%{query}%"
        sql += " ORDER BY atualizado_em DESC, id DESC LIMIT :limit"
        rows = db.execute(text(sql), params).mappings().all()
        items = [
            {
                **dict(row),
                "preco": float(row["preco"] or 0),
                "preco_antigo": float(row["preco_antigo"]) if row["preco_antigo"] is not None else None,
                "destaque": bool(row["destaque"]),
                "ativo": bool(row["ativo"]),
                "offer_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}",
                "store_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}&go=1",
            }
            for row in rows
        ]
        return {"count": len(items), "items": items}
    finally:
        db.close()


@app.post("/dashboard/api/offers/{offer_id}")
def dashboard_api_offer_update(offer_id: int, payload: DashboardOfferUpdatePayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        existing = db.execute(text("SELECT id FROM ofertas WHERE id = :id LIMIT 1"), {"id": offer_id}).scalar()
        if not existing:
            raise HTTPException(status_code=404, detail="Oferta nao encontrada.")

        title = (payload.titulo or "").strip()
        affiliate_url = (payload.url_afiliado or "").strip()
        if not title or not affiliate_url:
            raise HTTPException(status_code=400, detail="Titulo e URL afiliado sao obrigatorios.")

        slug = _normalize_offer_slug(db, payload.slug, title, ignore_id=offer_id)
        old_price = _parse_decimal(payload.preco_antigo, default=0.0) if payload.preco_antigo not in (None, "") else None
        expires_at = (payload.expira_em or "").strip() or None
        if expires_at and "T" in expires_at:
            expires_at = expires_at.replace("T", " ") + ":00"

        db.execute(
            text(
                """
                UPDATE ofertas
                SET slug = :slug,
                    titulo = :titulo,
                    descricao = :descricao,
                    preco = :preco,
                    preco_antigo = :preco_antigo,
                    loja = :loja,
                    url_afiliado = :url_afiliado,
                    cupom = :cupom,
                    imagem_url = :imagem_url,
                    categoria = :categoria,
                    tags = :tags,
                    destaque = :destaque,
                    ativo = :ativo,
                    expira_em = :expira_em,
                    atualizado_em = NOW()
                WHERE id = :id
                """
            ),
            {
                "id": offer_id,
                "slug": slug,
                "titulo": title,
                "descricao": (payload.descricao or "").strip() or None,
                "preco": _parse_decimal(payload.preco, default=0.0),
                "preco_antigo": old_price,
                "loja": (payload.loja or "").strip().lower() or None,
                "url_afiliado": affiliate_url,
                "cupom": (payload.cupom or "").strip() or None,
                "imagem_url": (payload.imagem_url or "").strip() or None,
                "categoria": (payload.categoria or "").strip() or "geral",
                "tags": (payload.tags or "").strip() or None,
                "destaque": 1 if payload.destaque else 0,
                "ativo": 1 if payload.ativo else 0,
                "expira_em": expires_at,
            },
        )
        db.commit()
        row = db.execute(
            text(
                """
                SELECT
                  id,
                  slug,
                  titulo,
                  descricao,
                  preco,
                  preco_antigo,
                  loja,
                  url_afiliado,
                  cupom,
                  imagem_url,
                  categoria,
                  tags,
                  destaque,
                  ativo,
                  expira_em,
                  atualizado_em
                FROM ofertas
                WHERE id = :id
                LIMIT 1
                """
            ),
            {"id": offer_id},
        ).mappings().one()
        item = {
            **dict(row),
            "preco": float(row["preco"] or 0),
            "preco_antigo": float(row["preco_antigo"]) if row["preco_antigo"] is not None else None,
            "destaque": bool(row["destaque"]),
            "ativo": bool(row["ativo"]),
            "offer_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}",
            "store_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}&go=1",
        }
        return {"ok": True, "item": item}
    finally:
        db.close()


@app.post("/dashboard/api/import/manual-page/preview")
def dashboard_api_manual_page_preview(payload: DashboardManualPagePayload, _: str = Depends(require_manager_auth)):
    try:
        provider, items = preview_page_url(payload.url, payload.limit)
        return {
            "provider": f"{provider}_page",
            "count": len(items),
            "url": payload.url,
            "items": items,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/api/import/file/preview")
async def dashboard_api_file_preview(
    provider: str = Form(...),
    upload: UploadFile = File(...),
    _: str = Depends(require_manager_auth),
):
    provider_key = _normalize_provider_key(provider)
    try:
        content = await upload.read()
        if provider_key == "shopee":
            items = preview_shopee_csv_file(content, upload.filename or "")
        elif provider_key == "amazon":
            items = preview_amazon_txt_file(content, upload.filename or "")
        elif provider_key == "amazon_html":
            items = preview_amazon_saved_html(content, upload.filename or "")
        elif provider_key == "mercadolivre":
            items = preview_mercadolivre_txt_file(content, upload.filename or "")
        else:
            raise HTTPException(status_code=501, detail=f"Importacao por arquivo ainda nao implementada para {provider}.")
        return {
            "provider": f"{provider_key}_file",
            "count": len(items),
            "filename": upload.filename,
            "items": items,
        }
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/dashboard/api/import/store/recategorize")
def dashboard_api_store_recategorize(payload: DashboardStoreRecategorizePayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        summary = recategorize_store_offers(
            db,
            store=(payload.store or "Shopee").strip() or "Shopee",
            only_uncategorized=bool(payload.only_uncategorized),
        )
        db.commit()
        return {"ok": True, "store": payload.store, **summary}
    finally:
        db.close()


@app.post("/dashboard/api/import/store/amazon/repair-affiliate")
def dashboard_api_amazon_repair_affiliate(payload: DashboardAmazonRepairPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        summary = repair_amazon_affiliate_links(db, only_inactive=bool(payload.only_inactive))
        db.commit()
        return {"ok": True, "store": "Amazon", **summary}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/import/store/mercadolivre/repair-affiliate")
def dashboard_api_mercadolivre_repair_affiliate(payload: DashboardAmazonRepairPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        summary = repair_mercadolivre_affiliate_links(db, only_inactive=bool(payload.only_inactive))
        db.commit()
        return {"ok": True, "store": "Mercado Livre", **summary}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/import/store/shopee/repair-affiliate")
def dashboard_api_shopee_repair_affiliate(payload: DashboardAmazonRepairPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        summary = repair_shopee_affiliate_links(db, only_inactive=bool(payload.only_inactive))
        db.commit()
        return {"ok": True, "store": "Shopee", **summary}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/import/store/mercadolivre/relink-existing/run")
def dashboard_api_mercadolivre_relink_existing_run(payload: DashboardMercadoLivreRelinkPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        items = [item.model_dump() for item in (payload.items or [])]
        if not items:
            raise HTTPException(status_code=400, detail="Nenhum link oficial do Mercado Livre recebido para vincular.")
        summary = relink_mercadolivre_existing_offers(db, items)
        db.commit()
        return {"ok": True, "provider": "mercadolivre_relink", **summary}
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/import/manual-links/run")
def dashboard_api_manual_links_run(payload: DashboardManualLinksPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        items = payload.items or []
        if not items:
            raise HTTPException(status_code=400, detail="Nenhum item manual recebido para importar.")

        processed_items: list[dict] = []
        for item in items:
            store = (item.store or _provider_label(_normalize_provider_key(item.provider))).strip()
            if store.lower() == "mercado livre" and not bool(item.affiliate_detected):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"O item '{item.title}' do Mercado Livre nao tem link oficial de afiliado. "
                        "Gere o link na Central/Barra de Afiliados e refaca o preview."
                    ),
                )
            if store.lower() == "mercado livre" and float(item.price or 0) <= 0:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"O item '{item.title}' do Mercado Livre esta com preco zerado ou ausente. "
                        "Revise o preco antes de importar."
                    ),
                )
            raw = {
                "title": item.title,
                "description": item.description or "",
                "price": float(item.price or 0),
                "old_price": float(item.old_price) if item.old_price not in (None, "") else None,
                "url": item.canonical_url or item.url,
                "image": item.image or "",
                "category": item.category or "ofertas",
                "coupon": item.coupon or None,
                "tags": item.tags or f"{(item.provider or 'manual').strip().lower()},manual",
                "featured": int(item.featured or 0),
                "affiliate_tag": item.affiliate_code or "",
                "item_id": item.item_id or None,
                "product_id": item.product_id or None,
            }
            processed_items.append(raw | {"store": store})

        summary = {"processed": 0, "created": 0, "updated": 0}
        imported: list[dict[str, Any]] = []
        for item in processed_items:
            normalized = normalize_offer(item, item["store"], item.get("affiliate_tag"))
            action = publish_offer(db, normalized)
            summary["processed"] += 1
            summary[action] += 1
            imported.append(
                {
                    "title": item["title"],
                    "store": item["store"],
                    "price": float(item["price"] or 0),
                    "url": item["url"],
                    "image": item["image"],
                    "category": item["category"],
                }
            )

        db.commit()
        return {
            "ok": True,
            "provider": "manual_links",
            "count": len(imported),
            "processed": summary["processed"],
            "created": summary["created"],
            "updated": summary["updated"],
            "items": imported,
        }
    except HTTPException:
        db.rollback()
        raise
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/social/run")
def dashboard_api_social_run(payload: DashboardSocialRunPayload, _: str = Depends(require_manager_auth)):
    return execute_social_run(payload.platform, payload.mode, payload.limit, payload.offer_ids)


@app.post("/dashboard/api/automation/import/run-now")
def dashboard_api_automation_import_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    providers = payload.providers or _env_settings_snapshot().get("auto_import_providers") or ["mercadolivre"]
    result = execute_import_run(providers)
    if scheduler is not None:
        scheduler._record_result("import", status="success" if not result.get("error") else "error", result=result)
    return result


@app.post("/dashboard/api/automation/social/run-now")
def dashboard_api_automation_social_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    settings = _env_settings_snapshot()
    platform = payload.platform or settings.get("auto_social_platform") or "facebook"
    mode = "feed"
    limit = int(payload.limit or settings.get("auto_social_limit") or 1)
    result = execute_social_run(platform, mode, limit)
    if scheduler is not None:
        scheduler._record_result("social", status="success" if not result.get("errors") else "error", result=result)
    return result


@app.post("/dashboard/api/automation/story/run-now")
def dashboard_api_automation_story_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    settings = _env_settings_snapshot()
    platform = payload.platform or settings.get("auto_story_platform") or "instagram"
    limit = int(payload.limit or settings.get("auto_story_limit") or 1)
    result = execute_social_run(platform, "story", limit)
    if scheduler is not None:
        scheduler._record_result("story", status="success" if not result.get("errors") else "error", result=result)
    return result


@app.post("/dashboard/api/settings")
def dashboard_api_settings_save(payload: DashboardSettingsPayload, _: str = Depends(require_manager_auth)):
    updates: dict[str, str] = {}

    if payload.manager_username is not None:
        username = payload.manager_username.strip() or "admin"
        updates["MANAGER_USERNAME"] = username

    password_changed = payload.manager_password is not None and payload.manager_password.strip() != ""
    if password_changed:
        updates["MANAGER_PASSWORD"] = payload.manager_password.strip()
    if payload.meta_access_token is not None and payload.meta_access_token.strip() != "":
        updates["META_ACCESS_TOKEN"] = payload.meta_access_token.strip()

    if payload.auto_import_enabled is not None:
        updates["AUTO_IMPORT_ENABLED"] = "true" if payload.auto_import_enabled else "false"
    if payload.auto_import_times is not None:
        updates["AUTO_IMPORT_TIMES"] = payload.auto_import_times.strip()
    if payload.auto_import_providers is not None:
        providers = [_normalize_provider_key(item) for item in payload.auto_import_providers if str(item).strip()]
        updates["AUTO_IMPORT_PROVIDERS"] = ",".join(dict.fromkeys(providers)) or "mercadolivre"

    if payload.auto_social_enabled is not None:
        updates["AUTO_SOCIAL_ENABLED"] = "true" if payload.auto_social_enabled else "false"
    if payload.auto_social_times is not None:
        updates["AUTO_SOCIAL_TIMES"] = payload.auto_social_times.strip()
    if payload.auto_social_platform is not None:
        updates["AUTO_SOCIAL_PLATFORM"] = payload.auto_social_platform.strip().lower() or "facebook"
    if payload.auto_social_mode is not None:
        updates["AUTO_SOCIAL_MODE"] = payload.auto_social_mode.strip().lower() or "feed"
    if payload.auto_social_limit is not None:
        updates["AUTO_SOCIAL_LIMIT"] = str(max(1, min(int(payload.auto_social_limit), 20)))
    if payload.auto_story_enabled is not None:
        updates["AUTO_STORY_ENABLED"] = "true" if payload.auto_story_enabled else "false"
    if payload.auto_story_times is not None:
        updates["AUTO_STORY_TIMES"] = payload.auto_story_times.strip()
    if payload.auto_story_platform is not None:
        updates["AUTO_STORY_PLATFORM"] = payload.auto_story_platform.strip().lower() or "instagram"
    if payload.auto_story_limit is not None:
        updates["AUTO_STORY_LIMIT"] = str(max(1, min(int(payload.auto_story_limit), 20)))
    if payload.sftp_host is not None:
        updates["SFTP_HOST"] = payload.sftp_host.strip()
    if payload.sftp_port is not None:
        updates["SFTP_PORT"] = str(max(1, int(payload.sftp_port)))
    if payload.sftp_username is not None:
        updates["SFTP_USERNAME"] = payload.sftp_username.strip()
    if payload.sftp_password is not None:
        updates["SFTP_PASSWORD"] = payload.sftp_password.strip()
    if payload.sftp_remote_path is not None:
        updates["SFTP_REMOTE_PATH"] = payload.sftp_remote_path.strip()
    if payload.stories_public_base_url is not None:
        updates["STORIES_PUBLIC_BASE_URL"] = payload.stories_public_base_url.strip()

    if not updates:
        return {"ok": True, "message": "Nenhuma alteracao recebida.", "settings": _env_settings_snapshot(), "reauth_required": False}

    _write_env_updates(updates)

    if scheduler is not None:
        scheduler._refresh_next_run("import")
        scheduler._refresh_next_run("social")
        scheduler._refresh_next_run("story")

    return {
        "ok": True,
        "message": "Configuracoes salvas no .env.",
        "settings": _env_settings_snapshot(),
        "reauth_required": password_changed,
    }


@app.post("/dashboard/api/deploy/stories")
def dashboard_api_deploy_stories(payload: DashboardDeployPayload, _: str = Depends(require_manager_auth)):
    try:
        return execute_deploy_stories(payload.only_files)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except paramiko.SSHException as e:
        raise HTTPException(status_code=502, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/dashboard/api/deploy/site")
def dashboard_api_deploy_site(_: str = Depends(require_manager_auth)):
    try:
        return execute_deploy_site()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except paramiko.SSHException as e:
        raise HTTPException(status_code=502, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/social/meta/post-previews")
def social_meta_post_previews(limit: int = 12, q: str = ""):
    db = SessionLocal()
    try:
        try:
            items = build_meta_post_previews(db, limit=limit, include_story_assets=False, search_query=q)
            return {"count": len(items), "items": items}
        except OperationalError as exc:
            return {
                "count": 0,
                "items": [],
                "database": {"ok": False, "error": _database_error_message(exc)},
            }
    finally:
        db.close()


@app.post("/social/meta/facebook/publish")
def social_meta_facebook_publish(payload: MetaFacebookPostPayload):
    try:
        return publish_facebook_post(message=payload.message, link=payload.link)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/social/meta/facebook/publish-batch")
def social_meta_facebook_publish_batch(payload: MetaFacebookBatchPayload):
    db = SessionLocal()
    try:
        return publish_facebook_offer_batch(db, limit=payload.limit, offer_ids=payload.offer_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))
    finally:
        db.close()


@app.post("/social/meta/instagram/create")
def social_meta_instagram_create(payload: MetaInstagramCreatePayload):
    try:
        return create_instagram_media_container(image_url=payload.image_url, caption=payload.caption)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/social/meta/story/generate")
def social_meta_story_generate(payload: MetaStoryPayload):
    db = SessionLocal()
    try:
        items = build_meta_post_previews(db, limit=max(1, min(payload.limit, 20)))
        if payload.offer_id is not None:
            items = [item for item in items if item["offer_id"] == payload.offer_id]
        if not items:
            raise HTTPException(status_code=404, detail="Nenhuma oferta encontrada para gerar story.")
        return {"count": len(items), "items": [item["story_payload"] | {"offer_id": item["offer_id"], "slug": item["slug"], "title": item["title"]} for item in items]}
    finally:
        db.close()


@app.post("/social/meta/instagram/story/create")
def social_meta_instagram_story_create(payload: MetaInstagramStoryCreatePayload):
    try:
        return create_instagram_story_container(payload.image_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.post("/social/meta/instagram/publish")
def social_meta_instagram_publish(payload: MetaInstagramPublishPayload):
    try:
        return publish_instagram_container(payload.creation_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        raise _raise_meta_http_error(e)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/integrations/shopee/product-offers-preview")
def shopee_product_offers_preview(keyword: str, limit: int = 10, pages: int = 1):
    try:
        offers = preview_shopee_offers(keyword=keyword, limit=limit, pages=pages)
        return {"keyword": keyword, "count": len(offers), "items": offers}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/integrations/meli/product-offers-preview")
def meli_product_offers_preview(keyword: str, limit: int = 10, pages: int = 1):
    try:
        offers = preview_mercadolivre_offers(keyword=keyword, limit=limit, pages=pages)
        return {"keyword": keyword, "count": len(offers), "items": offers}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/integrations/meli/oauth/url")
def meli_oauth_url():
    try:
        return build_auth_url()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/integrations/meli/callback")
def meli_oauth_callback(code: str | None = None, error: str | None = None, error_description: str | None = None):
    if error:
        return {
            "ok": False,
            "error": error,
            "error_description": error_description,
            "message": "Autorizacao negada ou bloqueada no retorno do Mercado Livre.",
        }

    if not code:
        return {"ok": False, "message": "Code nao recebido no callback."}

    try:
        tokens = exchange_code(code)
        return {
            "ok": True,
            "message": "Tokens gerados. Copie MELI_ACCESS_TOKEN e MELI_REFRESH_TOKEN para o .env.",
            "tokens": tokens,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/integrations/meli/oauth/exchange")
def meli_oauth_exchange(payload: MeliCodePayload):
    try:
        return exchange_code(payload.code)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/integrations/meli/oauth/refresh")
def meli_oauth_refresh(payload: MeliRefreshPayload):
    try:
        return refresh_token(payload.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/collect/run")
def run_collectors():
    db = SessionLocal()
    imported = {"Shopee": 0, "Mercado Livre": 0, "Amazon": 0, "TikTok": 0}

    try:
        imported["Shopee"] = _import_provider(db, "Shopee", fetch_shopee_offers())
        imported["Mercado Livre"] = _import_provider(db, "Mercado Livre", fetch_mercadolivre_offers())
        imported["Amazon"] = _import_provider(db, "Amazon", fetch_amazon_offers())
        imported["TikTok"] = _import_provider(db, "TikTok", fetch_tiktok_offers())

        db.commit()
        return {"imported": imported, "total": sum(imported.values())}
    finally:
        db.close()
