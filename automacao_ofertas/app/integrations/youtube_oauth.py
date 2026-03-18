from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import httpx
from dotenv import load_dotenv

ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
YOUTUBE_API_URL = "https://www.googleapis.com/youtube/v3"
YOUTUBE_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
YOUTUBE_THUMBNAIL_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/thumbnails/set"


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Variavel obrigatoria ausente: {name}")
    return value


def youtube_redirect_uri() -> str:
    return _required_env("YOUTUBE_REDIRECT_URI")


def build_youtube_auth_url(state: str) -> dict[str, str]:
    client_id = _required_env("YOUTUBE_CLIENT_ID")
    redirect_uri = youtube_redirect_uri()
    scope = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"

    url = (
        f"{GOOGLE_AUTH_URL}?response_type=code"
        f"&client_id={quote_plus(client_id)}"
        f"&redirect_uri={quote_plus(redirect_uri)}"
        f"&scope={quote_plus(scope)}"
        f"&access_type=offline"
        f"&prompt=consent"
        f"&include_granted_scopes=true"
        f"&state={quote_plus(state)}"
    )
    return {"auth_url": url, "state": state, "redirect_uri": redirect_uri}


def exchange_youtube_code(code: str) -> dict[str, Any]:
    payload = {
        "code": code,
        "client_id": _required_env("YOUTUBE_CLIENT_ID"),
        "client_secret": _required_env("YOUTUBE_CLIENT_SECRET"),
        "redirect_uri": youtube_redirect_uri(),
        "grant_type": "authorization_code",
    }
    with httpx.Client(timeout=30) as client:
        try:
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise ValueError(f"Erro OAuth YouTube (exchange): {detail}") from exc


def refresh_youtube_token(refresh_token_value: str) -> dict[str, Any]:
    payload = {
        "refresh_token": refresh_token_value,
        "client_id": _required_env("YOUTUBE_CLIENT_ID"),
        "client_secret": _required_env("YOUTUBE_CLIENT_SECRET"),
        "grant_type": "refresh_token",
    }
    with httpx.Client(timeout=30) as client:
        try:
            response = client.post(GOOGLE_TOKEN_URL, data=payload)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text if exc.response is not None else str(exc)
            raise ValueError(f"Erro OAuth YouTube (refresh): {detail}") from exc


def fetch_youtube_channel(access_token: str) -> dict[str, Any]:
    with httpx.Client(timeout=30) as client:
        response = client.get(
            f"{YOUTUBE_API_URL}/channels",
            params={"part": "snippet", "mine": "true"},
            headers={"Authorization": f"Bearer {access_token}"},
        )
        response.raise_for_status()
        payload = response.json()
    items = payload.get("items") or []
    if not items:
        raise ValueError("Nenhum canal do YouTube foi encontrado para essa conta.")
    channel = items[0]
    snippet = channel.get("snippet") or {}
    return {
        "id": channel.get("id"),
        "title": snippet.get("title") or "",
        "custom_url": snippet.get("customUrl") or "",
        "published_at": snippet.get("publishedAt") or "",
        "thumbnails": snippet.get("thumbnails") or {},
    }


def upload_youtube_short(
    access_token: str,
    video_path: Path,
    *,
    title: str,
    description: str,
    privacy_status: str = "private",
) -> dict[str, Any]:
    normalized_privacy = (privacy_status or "private").strip().lower()
    if normalized_privacy not in {"private", "unlisted", "public"}:
        normalized_privacy = "private"

    metadata = {
        "snippet": {
            "title": (title or "").strip()[:100],
            "description": (description or "").strip()[:5000],
            "categoryId": "22",
            "defaultLanguage": "pt-BR",
        },
        "status": {
            "privacyStatus": normalized_privacy,
            "selfDeclaredMadeForKids": False,
        },
    }

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(video_path.stat().st_size),
        "X-Upload-Content-Type": "video/mp4",
    }

    with httpx.Client(timeout=900) as client:
        start = client.post(
            YOUTUBE_UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            json=metadata,
        )
        try:
            start.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = start.text.strip() if start is not None else ""
            try:
                payload = start.json()
                error = payload.get("error") or {}
                errors = error.get("errors") or []
                reason = str((errors[0] or {}).get("reason") or "").strip() if errors else ""
                message = str(error.get("message") or "").strip()
                if reason == "uploadLimitExceeded":
                    raise ValueError(
                        "O YouTube bloqueou novos uploads dessa conta por enquanto (uploadLimitExceeded). "
                        "Espere a liberacao da conta/canal e tente novamente mais tarde."
                    ) from exc
                if message:
                    raise ValueError(f"Falha ao iniciar upload no YouTube: {message}") from exc
            except ValueError:
                raise
            except Exception:
                pass
            raise ValueError(f"Falha ao iniciar upload no YouTube: {detail or str(exc)}") from exc
        upload_url = start.headers.get("Location", "").strip()
        if not upload_url:
            raise ValueError("Google nao retornou a URL de upload resumivel do video.")

        with video_path.open("rb") as video_file:
            finish = client.put(
                upload_url,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "video/mp4",
                    "Content-Length": str(video_path.stat().st_size),
                },
                content=video_file.read(),
            )
        try:
            finish.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = finish.text.strip() if finish is not None else ""
            raise ValueError(f"Falha ao concluir upload no YouTube: {detail or str(exc)}") from exc
        return finish.json()


def upload_youtube_thumbnail(access_token: str, video_id: str, image_path: Path) -> dict[str, Any]:
    video_id = (video_id or "").strip()
    if not video_id:
        raise ValueError("video_id do YouTube nao informado para upload da thumbnail.")
    if not image_path.is_file():
        raise ValueError("Arquivo de thumbnail nao encontrado para upload.")

    with httpx.Client(timeout=180) as client:
        with image_path.open("rb") as image_file:
            response = client.post(
                YOUTUBE_THUMBNAIL_UPLOAD_URL,
                params={"videoId": video_id},
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "image/jpeg"},
                content=image_file.read(),
            )
        response.raise_for_status()
        return response.json()
