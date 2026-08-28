import json
import os
import re
import secrets
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import paramiko
from sqlalchemy import bindparam, text
from sqlalchemy.exc import OperationalError
from fastapi import Cookie, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel

from app.collectors.amazon import fetch_amazon_offers
from app.collectors.mercadolivre import fetch_mercadolivre_offers, preview_mercadolivre_offers
from app.collectors.shopee import enrich_shopee_offers_with_media, fetch_shopee_offers, preview_shopee_affiliate_links, preview_shopee_offers
from app.collectors.tiktok import fetch_tiktok_offers
from app.database import SessionLocal
from app.integrations.youtube_oauth import (
    _fetch_recent_uploads_from_channel_list,
    _split_channel_sources,
    _videos_details,
    build_channel_trend_ideas,
    build_youtube_auth_url,
    exchange_youtube_code,
    fetch_youtube_channel,
    refresh_youtube_token,
    upload_youtube_thumbnail,
    upload_youtube_short,
)
from app.integrations.mercadolivre_oauth import build_auth_url, exchange_code, refresh_token
from app.services.dashboard_data import (
    create_growth_target,
    delete_growth_target,
    ensure_dashboard_tables,
    fetch_dashboard_snapshot,
    fetch_growth_radar,
    update_growth_target,
    record_execution_error,
    record_execution_start,
    record_execution_success,
)
from app.services.category_inference import recategorize_store_offers
from app.services.automation_scheduler import AutomationScheduler
from app.services.manual_file_import import preview_amazon_txt_file, preview_mercadolivre_txt_file, preview_shopee_csv_file
from app.services.manual_link_import import preview_manual_affiliate_links
from app.services.manual_page_import import preview_amazon_saved_html, preview_page_url
from app.services.normalize import _has_meli_affiliate_marker, build_slug, normalize_offer
from app.services.publish import publish_offer
from app.services.store_maintenance import (
    preview_mercadolivre_existing_offer_relinks,
    repair_mercadolivre_product_links,
    relink_mercadolivre_existing_offers,
    repair_amazon_affiliate_links,
    repair_mercadolivre_affiliate_links,
    repair_shopee_affiliate_links,
)
from app.services.sftp_deploy import (
    deploy_automation_backend_via_sftp,
    deploy_public_site_via_sftp,
    deploy_stories_via_sftp,
    ensure_stories_dir,
    prune_local_generated_story_assets,
    prune_remote_generated_story_assets,
    sftp_settings_snapshot,
)
from app.services.youtube_channels import (
    bootstrap_legacy_env_youtube_channel,
    create_youtube_channel_profile,
    delete_youtube_channel_profile,
    fetch_youtube_channel_profiles,
    get_default_youtube_channel_profile,
    get_youtube_channel_profile,
    get_youtube_channel_profile_by_state,
    update_youtube_channel_profile,
)
from app.services.social_meta import (
    build_meta_post_previews,
    create_instagram_media_container,
    create_instagram_reel_container,
    create_instagram_story_container,
    download_source_video_asset,
    generate_reel_asset,
    generate_story_asset,
    get_instagram_content_publishing_limit,
    publish_facebook_offer_batch,
    publish_facebook_photo,
    publish_facebook_post,
    publish_facebook_reel,
    publish_facebook_story_photo,
    publish_facebook_story_video,
    publish_instagram_container,
    wait_for_instagram_container_ready,
)
from app.services.shopee_video import build_shopee_social_video_asset, queue_shopee_video_drafts_for_offers
from app.services.whatsapp_social import (
    list_whatsapp_groups,
    prepare_whatsapp_group_batch,
    prepare_whatsapp_web_batch,
    send_whatsapp_group_batch,
    whatsapp_settings_snapshot,
)
from app.services.youtube_cuts import analyze_youtube_video_for_cuts
from app.services.youtube_cuts import build_youtube_cut_publish_draft
from app.services.youtube_cuts import extract_youtube_video_id
from app.services.youtube_cuts import rerender_youtube_cut
from app.services.youtube_cuts import youtube_cut_video_path
from app.services.youtube_cuts import process_youtube_video_for_cuts
from app.services.youtube_cuts import youtube_cuts_asset_path

app = FastAPI(title="Automacao de Ofertas")
UI_DIR = Path(__file__).resolve().parents[1] / "dashboard_ui"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
scheduler: AutomationScheduler | None = None

AUTO_SOCIAL_SUPPORTED_MODES: dict[str, tuple[str, ...]] = {
    "facebook": ("feed", "reel", "reel_story", "feed_story_reel"),
    "instagram": ("feed", "reel", "story", "reel_story", "feed_story", "feed_story_reel"),
    "both": ("feed", "reel", "reel_story", "feed_story", "feed_story_reel"),
    "facebook_instagram": ("feed", "reel", "reel_story", "feed_story", "feed_story_reel"),
    "whatsapp": ("group",),
}


def _normalize_auto_social_action(platform: str | None, mode: str | None) -> tuple[str, str]:
    normalized_platform = (platform or "facebook").strip().lower() or "facebook"
    if normalized_platform not in AUTO_SOCIAL_SUPPORTED_MODES:
        normalized_platform = "facebook"
    allowed_modes = AUTO_SOCIAL_SUPPORTED_MODES[normalized_platform]
    normalized_mode = (mode or allowed_modes[0]).strip().lower() or allowed_modes[0]
    if normalized_platform in {"both", "facebook_instagram"} and normalized_mode == "feed":
        normalized_mode = "feed_story"
    if normalized_mode not in allowed_modes:
        normalized_mode = allowed_modes[0]
    if normalized_platform == "facebook_instagram":
        normalized_platform = "both"
    return normalized_platform, normalized_mode


def _cleanup_generated_publish_assets() -> dict[str, Any]:
    local_result = prune_local_generated_story_assets()
    remote_result: dict[str, Any] | None = None
    if sftp_settings_snapshot().get("enabled"):
        try:
            remote_result = prune_remote_generated_story_assets()
        except Exception as exc:  # noqa: BLE001
            remote_result = {"ok": False, "error": str(exc), "count": 0, "items": []}
    return {
        "ok": True,
        "retention_days": int(local_result.get("retention_days") or 0),
        "deleted_count": int(local_result.get("count") or 0) + int((remote_result or {}).get("count") or 0),
        "local": local_result,
        "remote": remote_result,
    }


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
    limit: int | None = None
    keyword: str | None = None


class DashboardShopeeReimportPayload(BaseModel):
    limit: int | None = 25


class DashboardShopeeLinksPayload(BaseModel):
    links: list[str]


class DashboardManualLinkItemPayload(BaseModel):
    provider: str
    store: str | None = None
    title: str
    description: str | None = None
    price: float | int | str = 0
    old_price: float | int | str | None = None
    discount_percent: int | float | str | None = None
    pix_price: float | int | str | None = None
    other_price: float | int | str | None = None
    installments: str | None = None
    shipping: str | None = None
    rating: float | int | str | None = None
    rating_count: int | float | str | None = None
    promotion_text: str | None = None
    url: str
    canonical_url: str | None = None
    image: str | None = None
    image_urls: list[str] | None = None
    category: str | None = None
    coupon: str | None = None
    tags: str | None = None
    featured: int | None = None
    video_url: str | None = None
    video_urls: list[str] | None = None
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


class DashboardYoutubeCutsAnalyzePayload(BaseModel):
    url: str


class DashboardYoutubeCutsProcessPayload(BaseModel):
    url: str
    limit: int = 5
    mode: str = "short"
    selection_strategy: str = "gemini_heuristica"
    risk_profile: str = "default"
    channel_profile_id: int | None = None
    burn_subtitles: bool = True


class DashboardYoutubeCutPublishPayload(BaseModel):
    job_id: str
    cut_id: int
    title: str | None = None
    description: str | None = None
    privacy_status: str = "public"
    publish_at: str | None = None
    mode: str = "short"
    channel_profile_id: int | None = None


class DashboardYoutubeChannelPayload(BaseModel):
    name: str
    handle: str | None = None
    notes: str | None = None
    source_channels: str | None = None
    avoid_terms: str | None = None
    preferred_terms: str | None = None
    viral_tone: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    redirect_uri: str | None = None
    is_default: bool = False
    is_active: bool = True


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
    auto_social_repeat_block_minutes: int | None = None
    auto_story_enabled: bool | None = None
    auto_story_times: str | None = None
    auto_story_platform: str | None = None
    auto_story_limit: int | None = None
    whatsapp_api_base_url: str | None = None
    whatsapp_api_token: str | None = None
    whatsapp_group_target: str | None = None
    sftp_host: str | None = None
    sftp_port: int | None = None
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_remote_path: str | None = None
    stories_public_base_url: str | None = None
    youtube_client_id: str | None = None
    youtube_client_secret: str | None = None
    youtube_redirect_uri: str | None = None
    ytdlp_cookies_from_browser: str | None = None
    ytdlp_cookies_file: str | None = None
    gemini_api_key: str | None = None
    gemini_model: str | None = None
    openai_api_key: str | None = None
    openai_shorts_rerank_model: str | None = None


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
    desconto_percentual: int | float | str | None = None
    preco_pix: float | int | str | None = None
    preco_outros_meios: float | int | str | None = None
    parcelas_texto: str | None = None
    frete_texto: str | None = None
    avaliacao_nota: float | int | str | None = None
    avaliacao_total: int | float | str | None = None
    promocao_texto: str | None = None
    loja: str | None = None
    url_afiliado: str
    cupom: str | None = None
    imagem_url: str | None = None
    imagem_urls: list[str] | None = None
    video_urls: list[str] | None = None
    categoria: str | None = None
    tags: str | None = None
    destaque: bool = False
    ativo: bool = True
    expira_em: str | None = None


class DashboardGrowthTargetPayload(BaseModel):
    platform: str
    target_type: str
    name: str
    handle: str | None = None
    url: str
    niche: str | None = None
    priority: str = "media"
    status: str = "novo"
    notes: str | None = None
    last_checked_at: str | None = None


def _bool_env(name: str, default: bool = False) -> bool:
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on", "sim"}


def _site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/")


def _decode_json_url_list(value: Any) -> list[str]:
    if isinstance(value, list):
        candidates = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if not isinstance(decoded, list):
            return []
        candidates = decoded

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        url = str(candidate or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        normalized.append(url)
    return normalized


def _normalize_growth_target_payload(payload: DashboardGrowthTargetPayload, *, partial: bool = False) -> dict[str, Any]:
    allowed_platforms = {"facebook", "instagram"}
    allowed_target_types = {"page", "group", "profile", "creator"}
    allowed_priorities = {"alta", "media", "baixa"}
    allowed_status = {"novo", "monitorando", "abordar_manual", "pronto_para_testar", "arquivado"}

    normalized_platform = (payload.platform or "").strip().lower()
    normalized_target_type = (payload.target_type or "").strip().lower()
    normalized_priority = (payload.priority or "media").strip().lower()
    normalized_status = (payload.status or "novo").strip().lower()
    normalized_name = (payload.name or "").strip()
    normalized_handle = (payload.handle or "").strip().lstrip("@")
    normalized_url = (payload.url or "").strip()
    normalized_niche = (payload.niche or "").strip()
    normalized_notes = (payload.notes or "").strip()
    normalized_last_checked = (payload.last_checked_at or "").strip().replace("T", " ")

    if normalized_platform not in allowed_platforms:
        raise ValueError("Plataforma de crescimento invalida. Use facebook ou instagram.")
    if normalized_target_type not in allowed_target_types:
        raise ValueError("Tipo de alvo invalido. Use page, group, profile ou creator.")
    if normalized_priority not in allowed_priorities:
        normalized_priority = "media"
    if normalized_status not in allowed_status:
        normalized_status = "novo"
    if not partial and not normalized_name:
        raise ValueError("Informe um nome para o alvo de crescimento.")
    if not partial and not normalized_url.startswith(("http://", "https://")):
        raise ValueError("Informe uma URL valida do Facebook ou Instagram.")

    return {
        "platform": normalized_platform,
        "target_type": normalized_target_type,
        "name": normalized_name[:180],
        "handle": normalized_handle[:180] or None,
        "url": normalized_url[:600],
        "niche": normalized_niche[:140] or None,
        "priority": normalized_priority,
        "status": normalized_status,
        "notes": normalized_notes[:4000] or None,
        "last_checked_at": normalized_last_checked[:19] or None,
    }


def _youtube_channel_profile_payload(payload: DashboardYoutubeChannelPayload, *, current: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized_name = (payload.name or "").strip()
    if not normalized_name:
        raise ValueError("Informe um nome para o perfil do canal do YouTube.")
    return {
        "name": normalized_name[:180],
        "handle": (payload.handle or "").strip().lstrip("@")[:180] or None,
        "notes": (payload.notes or "").strip()[:4000] or None,
        "source_channels": (payload.source_channels or "").strip()[:12000] or None,
        "avoid_terms": (payload.avoid_terms or "").strip()[:4000] or None,
        "preferred_terms": (payload.preferred_terms or "").strip()[:4000] or None,
        "viral_tone": (payload.viral_tone or "").strip()[:1200] or None,
        "client_id": (payload.client_id or "").strip()[:255] or None,
        "client_secret": ((payload.client_secret or "").strip() or (current or {}).get("client_secret") or None),
        "redirect_uri": (payload.redirect_uri or "").strip()[:600] or None,
        "is_default": bool(payload.is_default),
        "is_active": bool(payload.is_active),
    }


def _youtube_channel_public_profile(profile: dict[str, Any] | None) -> dict[str, Any] | None:
    if not profile:
        return None
    return {
        "id": int(profile.get("id") or 0),
        "slug": profile.get("slug") or "",
        "name": profile.get("name") or "",
        "handle": profile.get("handle") or "",
        "notes": profile.get("notes") or "",
        "source_channels": profile.get("source_channels") or "",
        "avoid_terms": profile.get("avoid_terms") or "",
        "preferred_terms": profile.get("preferred_terms") or "",
        "viral_tone": profile.get("viral_tone") or "",
        "client_id": profile.get("client_id") or "",
        "redirect_uri": profile.get("redirect_uri") or "",
        "is_default": bool(profile.get("is_default")),
        "is_active": bool(profile.get("is_active")),
        "channel_id": profile.get("channel_id") or "",
        "channel_title": profile.get("channel_title") or "",
        "channel_custom_url": profile.get("channel_custom_url") or "",
        "channel_thumbnail_url": profile.get("channel_thumbnail_url") or "",
        "authenticated": bool(profile.get("refresh_token")),
        "updated_at": profile.get("updated_at"),
    }


def _resolve_youtube_channel_profile(db, channel_profile_id: int | None = None, *, require_active: bool = True) -> dict[str, Any]:
    bootstrap_legacy_env_youtube_channel(db)
    profile = get_youtube_channel_profile(db, int(channel_profile_id)) if channel_profile_id else get_default_youtube_channel_profile(db)
    if not profile:
        raise ValueError("Nenhum perfil de canal do YouTube foi configurado ainda.")
    if require_active and not profile.get("is_active"):
        raise ValueError("O perfil de canal do YouTube selecionado esta desativado.")
    return profile


def _resolve_youtube_channel_profile_by_name(db, profile_name: str, *, require_active: bool = True) -> dict[str, Any]:
    bootstrap_legacy_env_youtube_channel(db)
    desired = str(profile_name or "").strip().lower()
    if not desired:
        raise ValueError("Nome do perfil de canal do YouTube nao informado.")
    for profile in fetch_youtube_channel_profiles(db):
        candidates = [
            str(profile.get("name") or "").strip().lower(),
            str(profile.get("handle") or "").strip().lower(),
            str(profile.get("channel_title") or "").strip().lower(),
            str(profile.get("slug") or "").strip().lower(),
        ]
        if desired in candidates:
            if require_active and not profile.get("is_active"):
                raise ValueError("O perfil de canal do YouTube selecionado esta desativado.")
            return profile
    raise ValueError(f"Perfil de canal do YouTube nao encontrado: {profile_name}")


def _youtube_profile_token_expired(profile: dict[str, Any], skew_seconds: int = 120) -> bool:
    raw = profile.get("token_expires_at")
    if not raw:
        return True
    try:
        expires_at = datetime.fromtimestamp(int(raw), tz=timezone.utc)
    except Exception:
        return True
    return expires_at <= datetime.now(timezone.utc) + timedelta(seconds=skew_seconds)


def _youtube_profile_token_updates(tokens: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    access_token = str(tokens.get("access_token") or "").strip()
    refresh_token_value = str(tokens.get("refresh_token") or "").strip()
    expires_in = int(tokens.get("expires_in") or 0)
    if access_token:
        updates["access_token"] = access_token
    if refresh_token_value:
        updates["refresh_token"] = refresh_token_value
    elif current.get("refresh_token"):
        updates["refresh_token"] = current.get("refresh_token")
    if expires_in > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        updates["token_expires_at"] = int(expires_at.timestamp())
    return updates


def _youtube_refresh_requires_reauth(error: Exception | str) -> bool:
    detail = str(error or "").lower()
    return "invalid_grant" in detail or "expired or revoked" in detail


def _youtube_reauth_message(profile: dict[str, Any] | None = None) -> str:
    profile_name = str((profile or {}).get("name") or "").strip()
    profile_label = f" para o perfil '{profile_name}'" if profile_name else ""
    return (
        f"A autenticacao do YouTube{profile_label} expirou ou foi revogada no Google. "
        "Reconecte o canal em /manager e rode novamente."
    )


def _youtube_mark_profile_reauth_required(db, profile: dict[str, Any]) -> dict[str, Any]:
    return update_youtube_channel_profile(
        db,
        int(profile["id"]),
        {
            "access_token": None,
            "refresh_token": None,
            "token_expires_at": None,
            "oauth_state": None,
        },
    )


def _youtube_auth_snapshot(channel_profile_id: int | None = None, *, refresh: bool = False) -> dict[str, Any]:
    db = SessionLocal()
    try:
        profiles = fetch_youtube_channel_profiles(db)
        selected = _resolve_youtube_channel_profile(db, channel_profile_id, require_active=False) if profiles else None
        snapshot = {
            "profiles": [
                {
                    "id": int(item["id"]),
                    "name": item["name"],
                    "handle": item.get("handle") or item.get("channel_custom_url") or "",
                    "is_default": bool(item.get("is_default")),
                    "is_active": bool(item.get("is_active")),
                    "authenticated": bool(item.get("refresh_token")) and not _youtube_profile_token_expired(item),
                    "channel_title": item.get("channel_title") or "",
                    "channel_custom_url": item.get("channel_custom_url") or "",
                }
                for item in profiles
            ],
            "selected_profile_id": int(selected["id"]) if selected else None,
            "profile": None,
            "client_id_configured": False,
            "client_secret_configured": False,
            "redirect_uri": "",
            "access_token_configured": False,
            "refresh_token_configured": False,
            "token_expired": True,
            "channel": None,
            "authenticated": False,
            "reauth_required": False,
            "error": "",
        }
        if not selected:
            return snapshot

        if refresh and selected.get("refresh_token") and (not selected.get("access_token") or _youtube_profile_token_expired(selected)):
            try:
                tokens = refresh_youtube_token(
                    str(selected.get("refresh_token") or ""),
                    client_id=str(selected.get("client_id") or ""),
                    client_secret=str(selected.get("client_secret") or ""),
                )
            except ValueError as exc:
                if _youtube_refresh_requires_reauth(exc):
                    selected = _youtube_mark_profile_reauth_required(db, selected)
                    snapshot["reauth_required"] = True
                    snapshot["error"] = _youtube_reauth_message(selected)
                else:
                    raise
            else:
                update_youtube_channel_profile(db, int(selected["id"]), _youtube_profile_token_updates(tokens, selected))
                selected = _resolve_youtube_channel_profile(db, int(selected["id"]), require_active=False)

        snapshot["profile"] = {
            "id": int(selected["id"]),
            "name": selected["name"],
            "handle": selected.get("handle") or "",
            "notes": selected.get("notes") or "",
            "is_default": bool(selected.get("is_default")),
            "is_active": bool(selected.get("is_active")),
            "channel_id": selected.get("channel_id") or "",
            "channel_title": selected.get("channel_title") or "",
            "channel_custom_url": selected.get("channel_custom_url") or "",
        }
        snapshot["client_id_configured"] = bool(selected.get("client_id"))
        snapshot["client_secret_configured"] = bool(selected.get("client_secret"))
        snapshot["redirect_uri"] = selected.get("redirect_uri") or ""
        snapshot["access_token_configured"] = bool(selected.get("access_token"))
        snapshot["refresh_token_configured"] = bool(selected.get("refresh_token"))
        snapshot["token_expired"] = _youtube_profile_token_expired(selected)

        access_token = str(selected.get("access_token") or "").strip()
        if access_token and not snapshot["token_expired"] and not snapshot["reauth_required"]:
            try:
                channel = fetch_youtube_channel(access_token)
                snapshot["channel"] = channel
                snapshot["authenticated"] = True
                if (
                    channel.get("id") != selected.get("channel_id")
                    or channel.get("title") != selected.get("channel_title")
                    or channel.get("custom_url") != selected.get("channel_custom_url")
                ):
                    thumbnails = channel.get("thumbnails") or {}
                    thumbnail_url = (
                        (thumbnails.get("high") or {}).get("url")
                        or (thumbnails.get("medium") or {}).get("url")
                        or (thumbnails.get("default") or {}).get("url")
                        or ""
                    )
                    update_youtube_channel_profile(
                        db,
                        int(selected["id"]),
                        {
                            "channel_id": channel.get("id") or None,
                            "channel_title": channel.get("title") or None,
                            "channel_custom_url": channel.get("custom_url") or None,
                            "channel_thumbnail_url": thumbnail_url or None,
                        },
                    )
                    selected = _resolve_youtube_channel_profile(db, int(selected["id"]), require_active=False)
                    snapshot["profile"]["channel_id"] = selected.get("channel_id") or ""
                    snapshot["profile"]["channel_title"] = selected.get("channel_title") or ""
                    snapshot["profile"]["channel_custom_url"] = selected.get("channel_custom_url") or ""
            except Exception as exc:  # noqa: BLE001
                snapshot["error"] = str(exc)
        return snapshot
    finally:
        db.close()


def _youtube_access_token_ready(channel_profile_id: int | None = None) -> tuple[str, dict[str, Any]]:
    db = SessionLocal()
    try:
        profile = _resolve_youtube_channel_profile(db, channel_profile_id)
        access_token = str(profile.get("access_token") or "").strip()
        if access_token and not _youtube_profile_token_expired(profile):
            return access_token, profile
        refresh_token_value = str(profile.get("refresh_token") or "").strip()
        if not refresh_token_value:
            raise ValueError("YouTube nao autenticado para esse perfil. Conecte a conta do canal antes de publicar.")
        try:
            tokens = refresh_youtube_token(
                refresh_token_value,
                client_id=str(profile.get("client_id") or ""),
                client_secret=str(profile.get("client_secret") or ""),
            )
        except ValueError as exc:
            if _youtube_refresh_requires_reauth(exc):
                _youtube_mark_profile_reauth_required(db, profile)
                raise ValueError(_youtube_reauth_message(profile)) from exc
            raise
        updated = update_youtube_channel_profile(db, int(profile["id"]), _youtube_profile_token_updates(tokens, profile))
        refreshed = str(updated.get("access_token") or "").strip()
        if not refreshed:
            raise ValueError("Nao foi possivel renovar o token do YouTube para esse perfil.")
        return refreshed, updated
    finally:
        db.close()


def _recent_site_social_offer_ids(db, limit: int = 20) -> list[int]:
    rows = db.execute(
        text(
            """
            SELECT result_json
            FROM automacao_execucoes
            WHERE tipo = 'social'
              AND status <> 'running'
              AND canal <> 'whatsapp'
              AND result_json IS NOT NULL
            ORDER BY criado_em DESC, id DESC
            LIMIT 80
            """
        )
    ).mappings().all()

    offer_ids: list[int] = []
    seen: set[int] = set()
    for row in rows:
        payload = row.get("result_json")
        if isinstance(payload, str):
            try:
                import json

                payload = json.loads(payload)
            except Exception:
                payload = None
        if not isinstance(payload, dict):
            continue
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            offer_id = int((item or {}).get("offer_id") or 0)
            if offer_id <= 0 or offer_id in seen:
                continue
            seen.add(offer_id)
            offer_ids.append(offer_id)
            if len(offer_ids) >= limit:
                return offer_ids
    return offer_ids


def _recent_social_offer_ids_within_minutes(db, minutes: int = 360) -> set[int]:
    minutes = max(1, int(minutes))
    rows = db.execute(
        text(
            """
            SELECT result_json
            FROM automacao_execucoes
            WHERE tipo = 'social'
              AND status <> 'running'
              AND canal <> 'whatsapp'
              AND result_json IS NOT NULL
              AND criado_em >= (NOW() - INTERVAL :minutes MINUTE)
            ORDER BY criado_em DESC, id DESC
            LIMIT 80
            """
        ),
        {"minutes": minutes},
    ).mappings().all()

    blocked_ids: set[int] = set()
    for row in rows:
        payload = row.get("result_json")
        if isinstance(payload, str):
            try:
                import json

                payload = json.loads(payload)
            except Exception:
                payload = None
        if not isinstance(payload, dict):
            continue
        items = payload.get("items") or []
        if not isinstance(items, list):
            continue
        for item in items:
            offer_id = int((item or {}).get("offer_id") or 0)
            if offer_id > 0:
                blocked_ids.add(offer_id)
    return blocked_ids


def _auto_social_candidate_score(item: dict[str, Any]) -> float:
    clicks = float(item.get("clicks") or 0)
    price = float(item.get("price") or 0)
    old_price = float(item.get("old_price") or 0)
    store_key = (str(item.get("store") or "") or "").strip().lower()
    has_source_video = str(item.get("video_url") or "").strip() != ""
    discount = 0.0
    if old_price > price > 0:
        discount = ((old_price - price) / old_price) * 100.0
    coupon_bonus = 5.0 if str(item.get("coupon") or "").strip() else 0.0
    video_bonus = 0.0
    if has_source_video:
        video_bonus = 12.0
        if store_key == "shopee":
            video_bonus = 120.0
    elif store_key == "shopee":
        video_bonus = -18.0
    return (clicks * 12.0) + (discount * 4.0) + coupon_bonus + min(price / 100.0, 15.0) + video_bonus


def _build_auto_social_candidate_previews(db, candidate_limit: int) -> list[dict[str, Any]]:
    preferred_stores = ["Amazon", "Mercado Livre", "Shopee"]
    per_store_limit = max(18, min(90, max(1, candidate_limit)))
    seen_offer_ids: set[int] = set()
    combined: list[dict[str, Any]] = []

    for store_name in preferred_stores:
        store_items = build_meta_post_previews(
            db,
            limit=per_store_limit,
            include_story_assets=False,
            include_square_card_assets=False,
            store_filter=store_name,
        )
        for item in store_items:
            offer_id = int(item.get("offer_id") or 0)
            if offer_id <= 0 or offer_id in seen_offer_ids:
                continue
            seen_offer_ids.add(offer_id)
            combined.append(item)

    fallback_items = build_meta_post_previews(
        db,
        limit=max(candidate_limit, 60),
        include_story_assets=False,
        include_square_card_assets=False,
    )
    for item in fallback_items:
        offer_id = int(item.get("offer_id") or 0)
        if offer_id <= 0 or offer_id in seen_offer_ids:
            continue
        seen_offer_ids.add(offer_id)
        combined.append(item)

    return combined


def _pick_auto_social_offer_ids(db, platform: str, mode: str, limit: int = 1) -> list[int]:
    candidate_limit = max(90, min(240, max(1, limit) * 90))
    recent_id_list = _recent_site_social_offer_ids(db, 20)
    recent_ids = set(recent_id_list)
    recent_block_minutes = _auto_social_repeat_block_minutes()
    blocked_recent_ids = _recent_social_offer_ids_within_minutes(db, recent_block_minutes)
    previews = _build_auto_social_candidate_previews(db, candidate_limit)
    candidates = [
        item
        for item in previews
        if int(item.get("offer_id") or 0) not in recent_ids
        and int(item.get("offer_id") or 0) not in blocked_recent_ids
    ]
    if not candidates:
        candidates = [item for item in previews if int(item.get("offer_id") or 0) not in blocked_recent_ids]
    if not candidates:
        candidates = [item for item in previews if int(item.get("offer_id") or 0) not in recent_ids]
    if not candidates:
        candidates = previews
    if not candidates:
        return []

    recent_store_counts: dict[str, int] = {}
    recent_store_positions: dict[str, int] = {}
    if recent_ids:
        placeholders = ",".join(str(int(offer_id)) for offer_id in sorted(recent_ids))
        store_rows = db.execute(
            text(
                f"""
                SELECT id, loja
                FROM ofertas
                WHERE id IN ({placeholders})
                """
            )
        ).mappings().all()
        for row in store_rows:
            store_key = (str(row.get("loja") or "") or "loja").strip().lower()
            recent_store_counts[store_key] = recent_store_counts.get(store_key, 0) + 1
        recent_store_map = {int(row["id"]): (str(row.get("loja") or "") or "loja").strip().lower() for row in store_rows}
        for index, offer_id in enumerate(recent_id_list):
            store_key = recent_store_map.get(int(offer_id))
            if store_key and store_key not in recent_store_positions:
                recent_store_positions[store_key] = index
        last_store_key = recent_store_map.get(int(recent_id_list[0])) if recent_id_list else None
    else:
        last_store_key = None

    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in candidates:
        store_key = (str(item.get("store") or "") or "loja").strip().lower()
        grouped.setdefault(store_key, []).append(item)

    for store_key, bucket in grouped.items():
        bucket.sort(
            key=lambda item: (
                -_auto_social_candidate_score(item),
                -float(item.get("clicks") or 0),
                str(item.get("title") or ""),
            )
        )

    ordered_store_keys = sorted(
        grouped.keys(),
        key=lambda key: (
            1 if len(grouped) > 1 and last_store_key and key == last_store_key else 0,
            0 if key not in recent_store_positions else 1,
            -recent_store_positions.get(key, len(recent_id_list) + 100),
            recent_store_counts.get(key, 0),
            -_auto_social_candidate_score(grouped[key][0]),
            key,
        ),
    )

    picked: list[int] = []
    used_offer_ids: set[int] = set()
    while len(picked) < limit:
        progressed = False
        for store_key in ordered_store_keys:
            bucket = grouped.get(store_key) or []
            while bucket and int(bucket[0].get("offer_id") or 0) in used_offer_ids:
                bucket.pop(0)
            if not bucket:
                continue
            offer_id = int(bucket.pop(0).get("offer_id") or 0)
            if offer_id <= 0 or offer_id in used_offer_ids:
                continue
            picked.append(offer_id)
            used_offer_ids.add(offer_id)
            progressed = True
            if len(picked) >= limit:
                break
        if not progressed:
            break

    return picked


def _auto_social_repeat_block_minutes() -> int:
    return max(60, int((os.getenv("AUTO_SOCIAL_REPEAT_BLOCK_MINUTES") or "1440").strip() or "1440"))


def _exclude_recent_social_offer_ids(db, offer_ids: list[int]) -> list[int]:
    if not offer_ids:
        return []
    blocked_recent_ids = _recent_social_offer_ids_within_minutes(db, _auto_social_repeat_block_minutes())
    return [offer_id for offer_id in offer_ids if int(offer_id) not in blocked_recent_ids]


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


def _price_is_zero_or_less(value: Any) -> bool:
    return _parse_decimal(value, default=0.0) <= 0


def _purge_zero_price_offers(db) -> int:
    ids = [
        int(row[0])
        for row in db.execute(text("SELECT id FROM ofertas WHERE COALESCE(preco, 0) <= 0")).all()
    ]
    if not ids:
        return 0

    db.execute(text("DELETE FROM cliques WHERE oferta_id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids})
    db.execute(text("DELETE FROM ofertas WHERE id IN :ids").bindparams(bindparam("ids", expanding=True)), {"ids": ids})
    return len(ids)


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
    auto_social_platform, auto_social_mode = _normalize_auto_social_action(
        os.getenv("AUTO_SOCIAL_PLATFORM") or "facebook",
        os.getenv("AUTO_SOCIAL_MODE") or "reel_story",
    )
    db = SessionLocal()
    try:
        youtube_profiles = fetch_youtube_channel_profiles(db)
    finally:
        db.close()
    return {
        "manager_username": _manager_credentials()[0],
        "meta_access_token_configured": bool((os.getenv("META_ACCESS_TOKEN") or "").strip()),
        "auto_import_enabled": _bool_env("AUTO_IMPORT_ENABLED", False),
        "auto_import_times": os.getenv("AUTO_IMPORT_TIMES") or "",
        "auto_import_providers": [item.strip() for item in (os.getenv("AUTO_IMPORT_PROVIDERS") or "mercadolivre").split(",") if item.strip()],
        "auto_social_enabled": _bool_env("AUTO_SOCIAL_ENABLED", False),
        "auto_social_times": os.getenv("AUTO_SOCIAL_TIMES") or "",
        "auto_social_platform": auto_social_platform,
        "auto_social_mode": auto_social_mode,
        "auto_social_limit": max(1, int((os.getenv("AUTO_SOCIAL_LIMIT") or "1").strip() or "1")),
        "auto_social_repeat_block_minutes": max(60, int((os.getenv("AUTO_SOCIAL_REPEAT_BLOCK_MINUTES") or "1440").strip() or "1440")),
        "auto_story_enabled": _bool_env("AUTO_STORY_ENABLED", False),
        "auto_story_times": os.getenv("AUTO_STORY_TIMES") or "",
        "auto_story_platform": (os.getenv("AUTO_STORY_PLATFORM") or "instagram").strip().lower(),
        "auto_story_limit": max(1, int((os.getenv("AUTO_STORY_LIMIT") or "1").strip() or "1")),
        "whatsapp": whatsapp_settings_snapshot(),
        "sftp": sftp_settings_snapshot(),
        "ai": {
            "gemini_api_key_configured": bool((os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()),
            "gemini_model": os.getenv("GEMINI_MODEL") or "gemini-2.0-flash",
            "openai_api_key_configured": bool((os.getenv("OPENAI_API_KEY") or "").strip()),
            "openai_shorts_rerank_model": os.getenv("OPENAI_SHORTS_RERANK_MODEL") or "gpt-4.1-mini",
        },
        "youtube": {
            "client_id": os.getenv("YOUTUBE_CLIENT_ID") or "",
            "client_secret_configured": bool((os.getenv("YOUTUBE_CLIENT_SECRET") or "").strip()),
            "redirect_uri": os.getenv("YOUTUBE_REDIRECT_URI") or "",
            "access_token_configured": bool((os.getenv("YOUTUBE_ACCESS_TOKEN") or "").strip()),
            "refresh_token_configured": bool((os.getenv("YOUTUBE_REFRESH_TOKEN") or "").strip()),
            "cookies_from_browser": os.getenv("YTDLP_COOKIES_FROM_BROWSER") or "",
            "cookies_file": os.getenv("YTDLP_COOKIES_FILE") or "",
            "channels": [
                {
                    "id": int(item["id"]),
                    "name": item["name"],
                    "handle": item.get("handle") or "",
                    "is_default": bool(item.get("is_default")),
                    "is_active": bool(item.get("is_active")),
                    "channel_title": item.get("channel_title") or "",
                    "channel_custom_url": item.get("channel_custom_url") or "",
                }
                for item in youtube_profiles
            ],
        },
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
    skipped = 0
    imported_items: list[dict[str, Any]] = []
    for raw in offers:
        if store.strip().lower() == "mercado livre" and not _has_meli_affiliate_marker(str(raw.get("url") or "")):
            skipped += 1
            continue
        normalized = normalize_offer(raw, store, raw.get("affiliate_tag"))
        action = publish_offer(db, normalized)
        processed += 1
        if action == "created":
            created += 1
        elif action == "updated":
            updated += 1
        else:
            skipped += 1
        if action in {"created", "updated"}:
            published_state = _published_offer_state(db, normalized)
            if published_state is not None:
                imported_items.append(
                    {
                        "offer_id": int(published_state["id"]),
                        "title": str(published_state.get("titulo") or normalized.titulo),
                        "action": action,
                        "has_video": bool(published_state.get("has_video")),
                    }
                )
    return {
        "processed": processed,
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "items": imported_items,
    }


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


def _http_error_detail(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        detail = (exc.response.text or "").strip()
        if detail:
            return detail
    return str(exc)


def _is_meta_remote_video_fetch_error(detail: str) -> bool:
    lowered = (detail or "").strip().lower()
    if not lowered:
        return False
    return (
        "video download failed" in lowered
        or "fwdproxy failed to fetch headers" in lowered
        or "failed to fetch headers" in lowered
    )


def _cache_busted_media_url(url: str, attempt: int) -> str:
    normalized = (url or "").strip()
    if normalized == "" or attempt <= 1:
        return normalized
    separator = "&" if "?" in normalized else "?"
    return f"{normalized}{separator}zp_retry={int(time.time())}-{attempt}"


def _create_instagram_story_video_container_with_retry(video_url: str) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            return create_instagram_story_container(video_url=_cache_busted_media_url(video_url, attempt))
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= 3 or not _is_meta_remote_video_fetch_error(_http_error_detail(exc)):
                raise
            time.sleep(4 * attempt)
    if last_exc is not None:
        raise last_exc
    raise ValueError("Falha ao criar o container de story em video no Instagram.")


def _create_instagram_reel_container_with_retry(video_url: str, caption: str) -> dict[str, Any]:
    last_exc: Exception | None = None
    for attempt in range(1, 4):
        try:
            return create_instagram_reel_container(
                video_url=_cache_busted_media_url(video_url, attempt),
                caption=caption,
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= 3 or not _is_meta_remote_video_fetch_error(_http_error_detail(exc)):
                raise
            time.sleep(4 * attempt)
    if last_exc is not None:
        raise last_exc
    raise ValueError("Falha ao criar o container de reel no Instagram.")


def _instagram_publish_capacity(required_posts: int = 1) -> dict[str, int]:
    limit_payload = get_instagram_content_publishing_limit()
    result = limit_payload.get("result") or {}
    quota_total = int(result.get("quota_total") or 0)
    quota_usage = int(result.get("quota_usage") or 0)
    quota_remaining = int(result.get("quota_remaining") or max(0, quota_total - quota_usage))
    return {
        "quota_total": quota_total,
        "quota_usage": quota_usage,
        "quota_remaining": quota_remaining,
        "required_posts": max(1, int(required_posts)),
    }


def _instagram_capacity_error(required_posts: int = 1) -> str:
    capacity = _instagram_publish_capacity(required_posts)
    return (
        "Limite da API do Instagram atingido ou insuficiente para esta execucao. "
        f"Restante: {capacity['quota_remaining']} de {capacity['quota_total']} no periodo de 24h. "
        f"Necessario agora: {capacity['required_posts']}."
    )


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


def _published_offer_state(db, normalized_offer) -> dict[str, Any] | None:
    normalized_store = str(normalized_offer.loja or "").strip().lower()
    normalized_url = str(normalized_offer.url_afiliado or "").strip()
    row = None
    if normalized_url:
        row = db.execute(
            PUBLISHED_OFFER_BY_URL_SQL,
            {"url": normalized_url, "store": normalized_store},
        ).mappings().first()
    if row is None:
        row = db.execute(
            PUBLISHED_OFFER_BY_SLUG_SQL,
            {"slug": build_slug(normalized_offer.titulo), "store": normalized_store},
        ).mappings().first()
    if row is None:
        return None
    payload = dict(row)
    payload["has_video"] = _shopee_offer_has_video_state(payload)
    return payload


SHOPEE_IMPORT_EXISTING_SQL = text(
    """
    SELECT
      id,
      url_afiliado,
      tags,
      video_urls_json,
      criado_em,
      atualizado_em
    FROM ofertas
    WHERE LOWER(loja) = 'shopee'
      AND url_afiliado IN :urls
    """
).bindparams(bindparam("urls", expanding=True))

PUBLISHED_OFFER_BY_URL_SQL = text(
    """
    SELECT
      id,
      titulo,
      tags,
      video_urls_json
    FROM ofertas
    WHERE url_afiliado = :url
      AND LOWER(loja) = :store
    LIMIT 1
    """
)

PUBLISHED_OFFER_BY_SLUG_SQL = text(
    """
    SELECT
      id,
      titulo,
      tags,
      video_urls_json
    FROM ofertas
    WHERE slug = :slug
      AND LOWER(loja) = :store
    LIMIT 1
    """
)

SHOPEE_IMPORT_EXISTING_TITLE_SQL = text(
    """
    SELECT
      id,
      titulo,
      url_afiliado,
      tags,
      video_urls_json,
      criado_em,
      atualizado_em
    FROM ofertas
    WHERE LOWER(loja) = 'shopee'
      AND titulo IN :titles
    ORDER BY atualizado_em DESC, id DESC
    """
).bindparams(bindparam("titles", expanding=True))


def _shopee_offer_title_key(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _shopee_offer_has_video_state(row: dict[str, Any]) -> bool:
    tags = str(row.get("tags") or "")
    if "offer_video_url:" in tags or "shopee_video_url:" in tags:
        return True
    return bool(_decode_json_url_list(row.get("video_urls_json")))


def _shopee_offer_is_recent(row: dict[str, Any]) -> bool:
    reference = row.get("atualizado_em") or row.get("criado_em")
    if reference is None:
        return False
    if isinstance(reference, str):
        try:
            reference = datetime.fromisoformat(reference.replace("Z", "+00:00"))
        except ValueError:
            return False
    if not isinstance(reference, datetime):
        return False
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - reference) < timedelta(hours=24)


def _preserve_existing_shopee_video_data(offer: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(offer)
    current_tags = [part.strip() for part in str(merged.get("tags") or "").split(",") if part.strip()]
    preserved_tags = [
        part.strip()
        for part in str(row.get("tags") or "").split(",")
        if part.strip().startswith(("offer_video_url:", "shopee_video_url:"))
    ]
    for tag in preserved_tags:
        if tag not in current_tags:
            current_tags.append(tag)
    if current_tags:
        merged["tags"] = ",".join(current_tags)

    existing_video_urls = _decode_json_url_list(row.get("video_urls_json"))
    if existing_video_urls:
        merged["video_urls"] = existing_video_urls
        merged["video_url"] = existing_video_urls[0]
    return merged


def _shopee_import_pool_limit(limit: int | None) -> int | None:
    normalized_limit = _normalize_import_limit(limit)
    if normalized_limit is None:
        return None
    return max(normalized_limit * 8, 40)


def _merge_shopee_import_candidate(base_item: dict[str, Any], enriched_item: dict[str, Any] | None = None) -> dict[str, Any]:
    merged_item = dict(base_item)
    if isinstance(enriched_item, dict):
        merged_item.update(enriched_item)

    merged_item["store"] = "Shopee"
    merged_item["provider"] = "shopee"

    if float(merged_item.get("price") or 0) <= 0 and float(base_item.get("price") or 0) > 0:
        merged_item["price"] = float(base_item.get("price") or 0)
    if (not merged_item.get("old_price")) and base_item.get("old_price") not in (None, ""):
        merged_item["old_price"] = base_item.get("old_price")
    if not str(merged_item.get("title") or "").strip():
        merged_item["title"] = base_item.get("title") or "Oferta Shopee"
    if not str(merged_item.get("description") or "").strip():
        merged_item["description"] = base_item.get("description") or "Oferta Shopee importada da busca."
    if not str(merged_item.get("category") or "").strip():
        merged_item["category"] = base_item.get("category") or "ofertas"
    if not str(merged_item.get("url") or "").strip():
        merged_item["url"] = base_item.get("url") or ""
    if not str(merged_item.get("canonical_url") or "").strip():
        merged_item["canonical_url"] = base_item.get("canonical_url") or merged_item.get("url") or ""
    if not str(merged_item.get("image") or "").strip() and str(base_item.get("image") or "").strip():
        merged_item["image"] = base_item.get("image")
    if not merged_item.get("image_urls") and base_item.get("image_urls"):
        merged_item["image_urls"] = base_item.get("image_urls")
    if not merged_item.get("video_urls") and base_item.get("video_urls"):
        merged_item["video_urls"] = base_item.get("video_urls")
    if not merged_item.get("video_url") and base_item.get("video_url"):
        merged_item["video_url"] = base_item.get("video_url")
    if not str(merged_item.get("tags") or "").strip():
        merged_item["tags"] = base_item.get("tags") or "shopee"
    return merged_item


def _shopee_candidate_has_video(offer: dict[str, Any]) -> bool:
    if str(offer.get("video_url") or "").strip():
        return True
    if any(str(url or "").strip() for url in (offer.get("video_urls") or [])):
        return True
    tags = str(offer.get("tags") or "")
    return "offer_video_url:" in tags or "shopee_video_url:" in tags


def _shopee_candidate_has_media(offer: dict[str, Any]) -> bool:
    if _shopee_candidate_has_video(offer):
        return True
    image_urls = [str(url or "").strip() for url in (offer.get("image_urls") or []) if str(url or "").strip()]
    if len(image_urls) >= 2:
        return True
    return str(offer.get("image") or "").strip() != ""


def _prepare_shopee_import_offers(
    db,
    offers: list[dict[str, Any]],
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if not offers:
        return [], {
            "offers_selected": 0,
            "recent_skipped": 0,
            "existing_video_skipped": 0,
            "existing_video_updated": 0,
        }

    target = max(1, int(limit)) if limit is not None else len(offers)
    candidates: list[dict[str, Any]] = []
    lookup_urls: list[str] = []
    for offer in offers:
        candidate = dict(offer)
        normalized = normalize_offer(candidate, "Shopee", candidate.get("affiliate_tag"))
        normalized_url = str(normalized.url_afiliado or "").strip()
        candidate["_job_affiliate_url"] = normalized_url
        candidate["_job_title_key"] = _shopee_offer_title_key(candidate.get("title"))
        candidates.append(candidate)
        if normalized_url:
            lookup_urls.append(normalized_url)
    lookup_titles = sorted({_shopee_offer_title_key(offer.get("title")) for offer in candidates if _shopee_offer_title_key(offer.get("title"))})

    existing_rows_by_url = (
        db.execute(SHOPEE_IMPORT_EXISTING_SQL, {"urls": sorted(set(lookup_urls))}).mappings().all()
        if lookup_urls
        else []
    )
    existing_rows_by_title = (
        db.execute(SHOPEE_IMPORT_EXISTING_TITLE_SQL, {"titles": lookup_titles}).mappings().all()
        if lookup_titles
        else []
    )
    existing_by_url = {str(row["url_afiliado"] or "").strip(): dict(row) for row in existing_rows_by_url}
    existing_by_title: dict[str, dict[str, Any]] = {}
    for row in existing_rows_by_title:
        title_key = _shopee_offer_title_key(row.get("titulo"))
        if title_key and title_key not in existing_by_title:
            existing_by_title[title_key] = dict(row)

    selected: list[dict[str, Any]] = []
    refresh_existing_video: list[dict[str, Any]] = []
    recent_skipped = 0
    existing_video_skipped = 0

    for candidate in candidates:
        existing = existing_by_url.get(str(candidate.get("_job_affiliate_url") or "").strip())
        if existing is None:
            existing = existing_by_title.get(str(candidate.get("_job_title_key") or "").strip())
        if existing and _shopee_offer_is_recent(existing):
            recent_skipped += 1
            continue
        if existing and _shopee_offer_has_video_state(existing):
            existing_video_skipped += 1
            if len(refresh_existing_video) < target:
                refresh_existing_video.append(_preserve_existing_shopee_video_data(candidate, existing))
            continue

        selected.append(candidate)
    selected_with_video: list[dict[str, Any]] = []
    selected_with_media: list[dict[str, Any]] = []
    selected_without_media: list[dict[str, Any]] = []
    scan_batch_size = max(1, min(10, target))

    for index in range(0, len(selected), scan_batch_size):
        batch = selected[index:index + scan_batch_size]
        try:
            enriched_batch = enrich_shopee_offers_with_media(batch) if batch else []
        except Exception:
            enriched_batch = []
        for batch_index, base_item in enumerate(batch):
            enriched_item = enriched_batch[batch_index] if batch_index < len(enriched_batch) and isinstance(enriched_batch[batch_index], dict) else {}
            merged_item = _merge_shopee_import_candidate(base_item, enriched_item)
            if _shopee_candidate_has_video(merged_item):
                selected_with_video.append(merged_item)
            elif _shopee_candidate_has_media(merged_item):
                selected_with_media.append(merged_item)
            else:
                selected_without_media.append(merged_item)

    enriched_selected = selected_with_video[:target]
    if len(enriched_selected) < target:
        remaining_slots = target - len(enriched_selected)
        enriched_selected.extend(selected_with_media[:remaining_slots])
    if len(enriched_selected) < target:
        remaining_slots = target - len(enriched_selected)
        enriched_selected.extend(selected_without_media[:remaining_slots])

    final_offers = enriched_selected + refresh_existing_video
    for offer in final_offers:
        offer.pop("_job_affiliate_url", None)
        offer.pop("_job_title_key", None)

    return final_offers, {
        "offers_selected": len(enriched_selected),
        "offers_with_video_selected": len(selected_with_video[:target]),
        "offers_with_media_selected": len(selected_with_media[: max(0, target - len(selected_with_video[:target]))]),
        "offers_without_media_selected": max(0, len(enriched_selected) - len(selected_with_video[:target]) - len(selected_with_media[: max(0, target - len(selected_with_video[:target]))])),
        "offers_scanned": len(selected),
        "recent_skipped": recent_skipped,
        "existing_video_skipped": existing_video_skipped,
        "existing_video_updated": len(refresh_existing_video),
    }


def _prepare_import_offers(
    db,
    key: str,
    offers: list[dict[str, Any]],
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    if key == "shopee":
        return _prepare_shopee_import_offers(db, offers, limit)
    if limit is not None:
        offers = offers[:limit]
    return offers, {"offers_selected": len(offers)}


def _fetch_provider_import_offers(
    db,
    key: str,
    limit: int | None = None,
    keyword: str | None = None,
) -> tuple[int, list[dict[str, Any]], dict[str, int]]:
    if key == "shopee":
        offers = fetch_shopee_offers(limit_override=_shopee_import_pool_limit(limit), keyword_override=keyword)
        offers_found = len(offers)
        prepared, meta = _prepare_import_offers(db, key, offers, limit)
        return offers_found, prepared, meta

    fetcher = _provider_fetcher(key)
    offers = fetcher()
    offers_found = len(offers)
    prepared, meta = _prepare_import_offers(db, key, offers, limit)
    return offers_found, prepared, meta


def _normalize_import_limit(limit: int | None) -> int | None:
    if limit in (None, "", 0):
        return None
    try:
        parsed = int(limit)
    except (TypeError, ValueError):
        return None
    return max(1, min(parsed, 100))


def execute_import_run(providers: list[str] | None = None, limit: int | None = None, keyword: str | None = None) -> dict:
    db = SessionLocal()
    items = providers or ["mercadolivre", "shopee", "amazon", "tiktok"]
    normalized_limit = _normalize_import_limit(limit)
    normalized_keyword = (keyword or "").strip() or None
    results = []

    try:
        for item in items:
            provider_key = _normalize_provider_key(item)
            run_id = record_execution_start(
                db,
                tipo="import",
                provider=provider_key,
                requested_count=normalized_limit or 0,
                payload={"provider": provider_key, "limit": normalized_limit, "keyword": normalized_keyword},
            )

            try:
                offers_found, offers, selection_meta = _fetch_provider_import_offers(
                    db,
                    provider_key,
                    normalized_limit,
                    normalized_keyword if provider_key == "shopee" else None,
                )
                import_summary = _import_provider(db, _provider_label(provider_key), offers)
                imported_without_video_ids: list[int] = []
                imported_without_video_titles: list[str] = []
                draft_summary: dict[str, Any] = {"count": 0, "created": 0, "updated": 0, "items": []}
                if provider_key == "shopee":
                    imported_without_video_ids = [
                        int(item["offer_id"])
                        for item in import_summary.get("items", [])
                        if int(item.get("offer_id") or 0) > 0 and not bool(item.get("has_video"))
                    ]
                    imported_without_video_titles = [
                        str(item.get("title") or "")
                        for item in import_summary.get("items", [])
                        if int(item.get("offer_id") or 0) > 0 and not bool(item.get("has_video"))
                    ]
                    if imported_without_video_ids:
                        draft_summary = queue_shopee_video_drafts_for_offers(db, imported_without_video_ids)
                db.commit()
                result = {
                    "provider": provider_key,
                    "processed": import_summary["processed"],
                    "created": import_summary["created"],
                    "updated": import_summary["updated"],
                    "skipped": import_summary.get("skipped", 0),
                    "imported": import_summary["processed"],
                    "offers_found": offers_found,
                    "offers_selected": int(selection_meta.get("offers_selected") or len(offers)),
                    "limit_requested": normalized_limit,
                    "keyword": normalized_keyword,
                    "recent_skipped": int(selection_meta.get("recent_skipped") or 0),
                    "existing_video_skipped": int(selection_meta.get("existing_video_skipped") or 0),
                    "existing_video_updated": int(selection_meta.get("existing_video_updated") or 0),
                    "offers_with_video_selected": int(selection_meta.get("offers_with_video_selected") or 0),
                    "offers_with_media_selected": int(selection_meta.get("offers_with_media_selected") or 0),
                    "offers_without_media_selected": int(selection_meta.get("offers_without_media_selected") or 0),
                    "offers_scanned": int(selection_meta.get("offers_scanned") or 0),
                    "imported_without_video_count": len(imported_without_video_ids),
                    "imported_without_video_titles": imported_without_video_titles[:10],
                    "shopee_video_drafts_created": int(draft_summary.get("created") or 0),
                    "shopee_video_drafts_updated": int(draft_summary.get("updated") or 0),
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
    if (platform or "").strip().lower() in AUTO_SOCIAL_SUPPORTED_MODES:
        platform, mode = _normalize_auto_social_action(platform, mode)
    else:
        platform = (platform or "").strip().lower()
        mode = (mode or "feed").strip().lower()
    limit = max(1, min(limit, 20))
    db = SessionLocal()
    requested_offer_ids = [int(item) for item in (offer_ids or []) if str(item).strip()]
    selected_offer_ids = list(requested_offer_ids)
    if selected_offer_ids and platform in {"facebook", "instagram", "both", "facebook_instagram"}:
        selected_offer_ids = _exclude_recent_social_offer_ids(db, selected_offer_ids)
        if not selected_offer_ids:
            raise HTTPException(
                status_code=400,
                detail=(
                    "As ofertas selecionadas manualmente foram bloqueadas por publicacao recente. "
                    "Escolha outro item ou aguarde o intervalo de repeticao."
                ),
            )
    if not requested_offer_ids and platform in {"facebook", "instagram", "both", "facebook_instagram"}:
        selected_offer_ids = _pick_auto_social_offer_ids(db, platform, mode, limit)
    if selected_offer_ids:
        limit = min(limit, len(selected_offer_ids))

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
            if int(result.get("count") or 0) > 0:
                result["asset_cleanup"] = _cleanup_generated_publish_assets()
            record_execution_success(db, run_id, processed_count=int(result["count"]), result=result)
            return {"run_id": run_id} | result

        if platform == "whatsapp" and mode == "group":
            result = send_whatsapp_group_batch(db, limit=limit, offer_ids=selected_offer_ids or None)
            record_execution_success(db, run_id, processed_count=int(result["count"]), result=result)
            return {"run_id": run_id} | result

        if platform == "whatsapp" and mode == "web":
            result = prepare_whatsapp_web_batch(db, limit=limit, offer_ids=selected_offer_ids or None)
            record_execution_success(db, run_id, processed_count=int(result["count"]), result=result)
            return {"run_id": run_id} | result

        previews = build_meta_post_previews(
            db,
            limit=limit,
            offer_ids=selected_offer_ids or None,
            include_story_assets=((platform == "instagram" and mode in {"story", "reel_story", "feed_story", "feed_story_reel"}) or (platform in {"both", "facebook_instagram", "facebook"} and mode in {"reel_story", "feed_story", "feed_story_reel"})),
            include_square_card_assets=(platform in {"facebook", "instagram", "both", "facebook_instagram"} and mode in {"feed", "story", "feed_story", "feed_story_reel"}),
        )
        if not previews:
            raise ValueError("Nao ha ofertas elegiveis para publicar.")

        def build_offer_media_payload(item: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": item["offer_id"],
                "slug": item["slug"],
                "titulo": item["title"],
                "preco": item["price"],
                "preco_antigo": item.get("old_price"),
                "loja": item["store"],
                "categoria": item["category"],
                "imagem_url": item["image_url"],
                "imagem_urls": item.get("image_gallery_urls") or [],
                "video_urls": item.get("video_gallery_urls") or [],
                "url_afiliado": item.get("cta_url"),
                "cupom": item.get("coupon"),
                "parcelas_texto": item.get("installments"),
                "preco_pix": item.get("pix_price"),
                "frete_texto": item.get("shipping"),
                "avaliacao_nota": item.get("rating"),
                "avaliacao_total": item.get("rating_count"),
                "promocao_texto": item.get("promotion_text"),
            }

        source_video_asset_cache: dict[int, tuple[dict[str, Any] | None, str | None, str | None]] = {}
        story_video_asset_cache: dict[int, tuple[dict[str, Any] | None, str, str | None, str | None]] = {}
        generated_shopee_video_asset_cache: dict[int, tuple[dict[str, Any] | None, str | None]] = {}

        def prepare_generated_shopee_video_asset(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
            offer_id = int(item.get("offer_id") or 0)
            if offer_id in generated_shopee_video_asset_cache:
                return generated_shopee_video_asset_cache[offer_id]

            try:
                asset = build_shopee_social_video_asset(offer_id=offer_id)
                generated_shopee_video_asset_cache[offer_id] = (asset, None)
            except Exception as exc:  # noqa: BLE001
                generated_shopee_video_asset_cache[offer_id] = (None, str(exc))
            return generated_shopee_video_asset_cache[offer_id]

        def prepare_reel_asset(item: dict[str, Any]) -> tuple[dict[str, Any], str, str | None, str | None]:
            offer = build_offer_media_payload(item)
            reel_source = "generated_art"
            reel_asset_error = None
            source_video_url = str(item.get("reel_payload", {}).get("source_video_url") or "").strip() or None

            if source_video_url:
                try:
                    reel_asset = download_source_video_asset(offer, source_video_url)
                    reel_source = "offer_source_video"
                    return reel_asset, reel_source, source_video_url, reel_asset_error
                except Exception as source_exc:  # noqa: BLE001
                    reel_asset_error = str(source_exc)

            shopee_asset, shopee_asset_error = prepare_generated_shopee_video_asset(item)
            if shopee_asset:
                return shopee_asset, "generated_social_video", source_video_url, reel_asset_error
            if shopee_asset_error:
                reel_asset_error = shopee_asset_error if not reel_asset_error else f"{reel_asset_error} | {shopee_asset_error}"

            reel_asset = generate_reel_asset(offer)
            return reel_asset, reel_source, source_video_url, reel_asset_error

        def prepare_source_video_asset(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, str | None]:
            offer_id = int(item.get("offer_id") or 0)
            if offer_id in source_video_asset_cache:
                return source_video_asset_cache[offer_id]

            offer = build_offer_media_payload(item)
            source_video_url = str(item.get("reel_payload", {}).get("source_video_url") or "").strip() or None
            if not source_video_url:
                source_video_asset_cache[offer_id] = (None, None, None)
                return source_video_asset_cache[offer_id]

            try:
                asset = download_source_video_asset(offer, source_video_url)
                source_video_asset_cache[offer_id] = (asset, source_video_url, None)
            except Exception as source_exc:  # noqa: BLE001
                source_video_asset_cache[offer_id] = (None, source_video_url, str(source_exc))
            return source_video_asset_cache[offer_id]

        def prepare_story_video_asset(item: dict[str, Any]) -> tuple[dict[str, Any] | None, str, str | None, str | None]:
            offer_id = int(item.get("offer_id") or 0)
            if offer_id in story_video_asset_cache:
                return story_video_asset_cache[offer_id]

            source_asset, source_video_url, source_video_error = prepare_source_video_asset(item)
            if not source_asset or not source_video_url:
                shopee_asset, shopee_asset_error = prepare_generated_shopee_video_asset(item)
                if shopee_asset:
                    story_video_asset_cache[offer_id] = (shopee_asset, "generated_social_video", source_video_url, source_video_error)
                    return story_video_asset_cache[offer_id]
                combined_error = source_video_error
                if shopee_asset_error:
                    combined_error = shopee_asset_error if not combined_error else f"{combined_error} | {shopee_asset_error}"
                story_video_asset_cache[offer_id] = (None, "", source_video_url, combined_error)
                return story_video_asset_cache[offer_id]
            story_video_asset_cache[offer_id] = (source_asset, "offer_source_video", source_video_url, source_video_error)
            return story_video_asset_cache[offer_id]

        def publish_facebook_story_with_fallback(item: dict[str, Any], combined_item: dict[str, Any]) -> bool:
            story_video_asset, story_video_source, source_video_url, source_video_error = prepare_story_video_asset(item)
            if source_video_error:
                combined_item["facebook_story_video_error"] = source_video_error
                if source_video_url:
                    combined_item["facebook_story_source_video_url"] = source_video_url

            if story_video_asset:
                try:
                    published_video_story = publish_facebook_story_video(story_video_asset["file_path"])
                    combined_item["facebook_story_result"] = published_video_story["result"]
                    combined_item["facebook_story_video_id"] = published_video_story["video_id"]
                    combined_item["facebook_story_source"] = story_video_source or "source_video"
                    return True
                except Exception as exc:  # noqa: BLE001
                    combined_item["facebook_story_video_error"] = str(exc)

            try:
                story_filename = item["story_payload"]["image_url"].rstrip("/").split("/")[-1]
                deploy_result = deploy_stories_via_sftp(only_files=[story_filename])
                facebook_story = publish_facebook_story_photo(item["story_payload"]["image_url"])
                combined_item["facebook_story_deploy"] = deploy_result
                combined_item["facebook_story_result"] = facebook_story["result"]
                combined_item["facebook_story_source"] = "image"
                return True
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "offer_id": item["offer_id"],
                        "title": item["title"],
                        "platform": "facebook_story",
                        "error": _http_error_detail(exc),
                    }
                )
                return False

        def publish_instagram_story_with_fallback(item: dict[str, Any], combined_item: dict[str, Any]) -> bool:
            story_video_asset, story_video_source, source_video_url, source_video_error = prepare_story_video_asset(item)
            if source_video_error:
                combined_item["instagram_story_video_error"] = source_video_error
                if source_video_url:
                    combined_item["instagram_story_source_video_url"] = source_video_url

            if story_video_asset:
                try:
                    deploy_stories_via_sftp(only_files=[story_video_asset["filename"]])
                    created_story = _create_instagram_story_video_container_with_retry(story_video_asset["public_url"])
                    published_story = publish_instagram_container(created_story["result"]["id"])
                    combined_item["story_creation_id"] = created_story["result"]["id"]
                    combined_item["story_result"] = published_story["result"]
                    combined_item["story_source"] = story_video_source or "source_video"
                    return True
                except Exception as exc:  # noqa: BLE001
                    combined_item["instagram_story_video_error"] = _http_error_detail(exc)

            try:
                story_filename = item["story_payload"]["image_url"].rstrip("/").split("/")[-1]
                deploy_result = deploy_stories_via_sftp(only_files=[story_filename])
                created_story = create_instagram_story_container(image_url=item["story_payload"]["image_url"])
                published_story = publish_instagram_container(created_story["result"]["id"])
                combined_item["story_deploy"] = deploy_result
                combined_item["story_creation_id"] = created_story["result"]["id"]
                combined_item["story_result"] = published_story["result"]
                combined_item["story_source"] = "image"
                return True
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "offer_id": item["offer_id"],
                        "title": item["title"],
                        "platform": "instagram_story",
                        "error": _http_error_detail(exc),
                    }
                )
                return False

        items = []
        errors = []
        warnings = []
        instagram_posts_required = 0
        if platform == "instagram":
            if mode in {"reel_story", "feed_story"}:
                instagram_posts_required = len(previews) * 2
            elif mode == "feed_story_reel":
                instagram_posts_required = len(previews) * 3
            else:
                instagram_posts_required = len(previews)
        elif platform in {"both", "facebook_instagram"}:
            if mode in {"reel_story", "feed_story"}:
                instagram_posts_required = len(previews) * 2
            elif mode == "feed_story_reel":
                instagram_posts_required = len(previews) * 3
            elif mode in {"feed", "reel"}:
                instagram_posts_required = len(previews)

        instagram_capacity_error = ""
        if instagram_posts_required > 0:
            try:
                capacity = _instagram_publish_capacity(instagram_posts_required)
                if capacity["quota_remaining"] < instagram_posts_required:
                    instagram_capacity_error = _instagram_capacity_error(instagram_posts_required)
            except Exception as exc:  # noqa: BLE001
                instagram_capacity_error = _http_error_detail(exc)
        instagram_skip_for_combined = bool(instagram_capacity_error and platform in {"both", "facebook_instagram"})
        if instagram_skip_for_combined:
            warnings.append({"platform": "instagram", "warning": instagram_capacity_error})
        if platform == "facebook" and mode == "reel_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                if publish_facebook_story_with_fallback(item, combined_item):
                    success_for_item = True

                try:
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    published = publish_facebook_reel(
                        video_path=reel_asset["file_path"],
                        description=item["reel_payload"]["caption"],
                    )
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url or None
                    combined_item["source_video_error"] = reel_asset_error
                    combined_item["video_id"] = published["video_id"]
                    combined_item["publish_result"] = published["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook_reel",
                            "error": str(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        elif platform == "facebook" and mode == "feed_story_reel":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    image_filename = (item.get("facebook_payload", {}).get("image_filename") or "").strip()
                    if image_filename:
                        deploy_stories_via_sftp(only_files=[image_filename])
                    facebook_result = publish_facebook_photo(
                        image_url=item["facebook_payload"]["image_url"],
                        caption=item["facebook_payload"]["message"],
                    )
                    combined_item["facebook_result"] = facebook_result["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook_feed",
                            "error": str(exc),
                        }
                    )

                if publish_facebook_story_with_fallback(item, combined_item):
                    success_for_item = True

                try:
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    published = publish_facebook_reel(
                        video_path=reel_asset["file_path"],
                        description=item["reel_payload"]["caption"],
                    )
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url or None
                    combined_item["source_video_error"] = reel_asset_error
                    combined_item["video_id"] = published["video_id"]
                    combined_item["publish_result"] = published["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook_reel",
                            "error": str(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        elif platform in {"both", "facebook_instagram"} and mode == "feed":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                facebook_ok = False
                instagram_ok = False

                try:
                    image_filename = (item.get("facebook_payload", {}).get("image_filename") or "").strip()
                    if image_filename:
                        deploy_stories_via_sftp(only_files=[image_filename])
                    facebook_result = publish_facebook_photo(
                        image_url=item["facebook_payload"]["image_url"],
                        caption=item["facebook_payload"]["message"],
                    )
                    combined_item["facebook_result"] = facebook_result["result"]
                    facebook_ok = True
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
                    if instagram_skip_for_combined:
                        combined_item["instagram_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    feed_filename = (item.get("instagram_payload", {}).get("image_filename") or "").strip()
                    if feed_filename:
                        deploy_stories_via_sftp(only_files=[feed_filename])
                    created = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published = publish_instagram_container(created["result"]["id"])
                    combined_item["instagram_creation_id"] = created["result"]["id"]
                    combined_item["instagram_result"] = published["result"]
                    instagram_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram",
                            "error": _http_error_detail(exc),
                        }
                    )

                if facebook_ok or instagram_ok:
                    items.append(combined_item)
        elif platform in {"both", "facebook_instagram"} and mode == "reel_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                facebook_story_ok = False
                facebook_reel_ok = False
                instagram_story_ok = False
                instagram_reel_ok = False

                if publish_facebook_story_with_fallback(item, combined_item):
                    facebook_story_ok = True

                try:
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url
                    combined_item["source_video_error"] = reel_asset_error
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "reel_asset",
                            "error": str(exc),
                        }
                    )
                    reel_asset = None

                if reel_asset:
                    try:
                        published = publish_facebook_reel(
                            video_path=reel_asset["file_path"],
                            description=item["reel_payload"]["caption"],
                        )
                        combined_item["video_id"] = published["video_id"]
                        combined_item["facebook_reel_result"] = published["result"]
                        facebook_reel_ok = True
                    except Exception as exc:  # noqa: BLE001
                        errors.append(
                            {
                                "offer_id": item["offer_id"],
                                "title": item["title"],
                                "platform": "facebook_reel",
                                "error": str(exc),
                            }
                        )

                try:
                    if instagram_skip_for_combined:
                        combined_item["instagram_story_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    if publish_instagram_story_with_fallback(item, combined_item):
                        instagram_story_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": _http_error_detail(exc),
                        }
                    )

                if reel_asset:
                    try:
                        if instagram_skip_for_combined:
                            combined_item["instagram_reel_skipped_reason"] = instagram_capacity_error
                            raise StopIteration
                        if instagram_capacity_error:
                            raise ValueError(instagram_capacity_error)
                        deploy_stories_via_sftp(only_files=[reel_asset["filename"]])
                        created_reel = _create_instagram_reel_container_with_retry(
                            reel_asset["public_url"],
                            item["reel_payload"]["caption"],
                        )
                        status_payload = wait_for_instagram_container_ready(created_reel["result"]["id"])
                        published_reel = publish_instagram_container(created_reel["result"]["id"])
                        combined_item["instagram_reel_creation_id"] = created_reel["result"]["id"]
                        combined_item["instagram_reel_status"] = status_payload["result"]
                        combined_item["instagram_result"] = published_reel["result"]
                        instagram_reel_ok = True
                    except StopIteration:
                        pass
                    except Exception as exc:  # noqa: BLE001
                        errors.append(
                            {
                                "offer_id": item["offer_id"],
                                "title": item["title"],
                                "platform": "instagram_reel",
                                "error": _http_error_detail(exc),
                            }
                        )

                if facebook_story_ok or facebook_reel_ok or instagram_story_ok or instagram_reel_ok:
                    items.append(combined_item)
        elif platform in {"both", "facebook_instagram"} and mode == "feed_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                facebook_ok = False
                facebook_story_ok = False
                instagram_feed_ok = False
                instagram_story_ok = False

                try:
                    image_filename = (item.get("facebook_payload", {}).get("image_filename") or "").strip()
                    if image_filename:
                        deploy_stories_via_sftp(only_files=[image_filename])
                    facebook_result = publish_facebook_photo(
                        image_url=item["facebook_payload"]["image_url"],
                        caption=item["facebook_payload"]["message"],
                    )
                    combined_item["facebook_result"] = facebook_result["result"]
                    facebook_ok = True
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
                    if instagram_skip_for_combined:
                        combined_item["instagram_feed_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    feed_filename = (item.get("instagram_payload", {}).get("image_filename") or "").strip()
                    if feed_filename:
                        deploy_stories_via_sftp(only_files=[feed_filename])
                    created_feed = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published_feed = publish_instagram_container(created_feed["result"]["id"])
                    combined_item["feed_creation_id"] = created_feed["result"]["id"]
                    combined_item["feed_result"] = published_feed["result"]
                    instagram_feed_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_feed",
                            "error": _http_error_detail(exc),
                        }
                    )

                if publish_facebook_story_with_fallback(item, combined_item):
                    facebook_story_ok = True
                try:
                    if instagram_skip_for_combined:
                        combined_item["instagram_story_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    if publish_instagram_story_with_fallback(item, combined_item):
                        instagram_story_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook_instagram_story",
                            "error": _http_error_detail(exc),
                        }
                    )

                if facebook_ok or facebook_story_ok or instagram_feed_ok or instagram_story_ok:
                    items.append(combined_item)
        elif platform in {"both", "facebook_instagram"} and mode == "feed_story_reel":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                facebook_ok = False
                facebook_story_ok = False
                facebook_reel_ok = False
                instagram_feed_ok = False
                instagram_story_ok = False
                instagram_reel_ok = False

                try:
                    image_filename = (item.get("facebook_payload", {}).get("image_filename") or "").strip()
                    if image_filename:
                        deploy_stories_via_sftp(only_files=[image_filename])
                    facebook_result = publish_facebook_photo(
                        image_url=item["facebook_payload"]["image_url"],
                        caption=item["facebook_payload"]["message"],
                    )
                    combined_item["facebook_result"] = facebook_result["result"]
                    facebook_ok = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook",
                            "error": str(exc),
                        }
                    )

                if publish_facebook_story_with_fallback(item, combined_item):
                    facebook_story_ok = True

                try:
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url
                    combined_item["source_video_error"] = reel_asset_error
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "reel_asset",
                            "error": str(exc),
                        }
                    )
                    reel_asset = None

                if reel_asset:
                    try:
                        published = publish_facebook_reel(
                            video_path=reel_asset["file_path"],
                            description=item["reel_payload"]["caption"],
                        )
                        combined_item["video_id"] = published["video_id"]
                        combined_item["facebook_reel_result"] = published["result"]
                        facebook_reel_ok = True
                    except Exception as exc:  # noqa: BLE001
                        errors.append(
                            {
                                "offer_id": item["offer_id"],
                                "title": item["title"],
                                "platform": "facebook_reel",
                                "error": str(exc),
                            }
                        )

                try:
                    if instagram_skip_for_combined:
                        combined_item["instagram_feed_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    feed_filename = (item.get("instagram_payload", {}).get("image_filename") or "").strip()
                    if feed_filename:
                        deploy_stories_via_sftp(only_files=[feed_filename])
                    created_feed = create_instagram_media_container(
                        image_url=item["instagram_payload"]["image_url"],
                        caption=item["instagram_payload"]["caption"],
                    )
                    published_feed = publish_instagram_container(created_feed["result"]["id"])
                    combined_item["feed_creation_id"] = created_feed["result"]["id"]
                    combined_item["feed_result"] = published_feed["result"]
                    instagram_feed_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_feed",
                            "error": _http_error_detail(exc),
                        }
                    )

                try:
                    if instagram_skip_for_combined:
                        combined_item["instagram_story_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    if publish_instagram_story_with_fallback(item, combined_item):
                        instagram_story_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": _http_error_detail(exc),
                        }
                    )

                if reel_asset:
                    try:
                        if instagram_skip_for_combined:
                            combined_item["instagram_reel_skipped_reason"] = instagram_capacity_error
                            raise StopIteration
                        if instagram_capacity_error:
                            raise ValueError(instagram_capacity_error)
                        deploy_stories_via_sftp(only_files=[reel_asset["filename"]])
                        created_reel = _create_instagram_reel_container_with_retry(
                            reel_asset["public_url"],
                            item["reel_payload"]["caption"],
                        )
                        status_payload = wait_for_instagram_container_ready(created_reel["result"]["id"])
                        published_reel = publish_instagram_container(created_reel["result"]["id"])
                        combined_item["instagram_reel_creation_id"] = created_reel["result"]["id"]
                        combined_item["instagram_reel_status"] = status_payload["result"]
                        combined_item["instagram_result"] = published_reel["result"]
                        instagram_reel_ok = True
                    except StopIteration:
                        pass
                    except Exception as exc:  # noqa: BLE001
                        errors.append(
                            {
                                "offer_id": item["offer_id"],
                                "title": item["title"],
                                "platform": "instagram_reel",
                                "error": _http_error_detail(exc),
                            }
                        )

                if facebook_ok or facebook_story_ok or facebook_reel_ok or instagram_feed_ok or instagram_story_ok or instagram_reel_ok:
                    items.append(combined_item)
        elif platform == "facebook" and mode == "reel":
            for item in previews:
                try:
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
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
                            "reel_source": reel_source,
                            "source_video_url": source_video_url or None,
                            "source_video_error": reel_asset_error,
                            "video_id": published["video_id"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": str(exc)})
        elif platform in {"both", "facebook_instagram"} and mode == "reel":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                facebook_ok = False
                instagram_ok = False

                try:
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url
                    combined_item["source_video_error"] = reel_asset_error
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "reel_asset",
                            "error": str(exc),
                        }
                    )
                    continue

                try:
                    published = publish_facebook_reel(
                        video_path=reel_asset["file_path"],
                        description=item["reel_payload"]["caption"],
                    )
                    combined_item["video_id"] = published["video_id"]
                    combined_item["facebook_result"] = published["result"]
                    facebook_ok = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "facebook_reel",
                            "error": str(exc),
                        }
                    )

                try:
                    if instagram_skip_for_combined:
                        combined_item["instagram_skipped_reason"] = instagram_capacity_error
                        raise StopIteration
                    deploy_stories_via_sftp(only_files=[reel_asset["filename"]])
                    created = _create_instagram_reel_container_with_retry(
                        reel_asset["public_url"],
                        item["reel_payload"]["caption"],
                    )
                    status_payload = wait_for_instagram_container_ready(created["result"]["id"])
                    published = publish_instagram_container(created["result"]["id"])
                    combined_item["instagram_creation_id"] = created["result"]["id"]
                    combined_item["instagram_status"] = status_payload["result"]
                    combined_item["instagram_result"] = published["result"]
                    instagram_ok = True
                except StopIteration:
                    pass
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_reel",
                            "error": _http_error_detail(exc),
                        }
                    )

                if facebook_ok or instagram_ok:
                    items.append(combined_item)
        elif platform == "instagram" and mode == "feed":
            for item in previews:
                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    feed_filename = (item.get("instagram_payload", {}).get("image_filename") or "").strip()
                    if feed_filename:
                        deploy_stories_via_sftp(only_files=[feed_filename])
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
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": _http_error_detail(exc)})
        elif platform == "instagram" and mode == "reel":
            for item in previews:
                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    deploy_stories_via_sftp(only_files=[reel_asset["filename"]])
                    created = _create_instagram_reel_container_with_retry(
                        reel_asset["public_url"],
                        item["reel_payload"]["caption"],
                    )
                    status_payload = wait_for_instagram_container_ready(created["result"]["id"])
                    published = publish_instagram_container(created["result"]["id"])
                    items.append(
                        {
                            "offer_id": item["offer_id"],
                            "slug": item["slug"],
                            "title": item["title"],
                            "reel_file": reel_asset["filename"],
                            "reel_source": reel_source,
                            "source_video_url": source_video_url,
                            "source_video_error": reel_asset_error,
                            "creation_id": created["result"]["id"],
                            "status_result": status_payload["result"],
                            "publish_result": published["result"],
                        }
                    )
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_reel",
                            "error": _http_error_detail(exc),
                        }
                    )
        elif platform == "instagram" and mode == "story":
            for item in previews:
                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    combined_item = {
                        "offer_id": item["offer_id"],
                        "slug": item["slug"],
                        "title": item["title"],
                    }
                    if publish_instagram_story_with_fallback(item, combined_item):
                        items.append(combined_item)
                except Exception as exc:  # noqa: BLE001
                    errors.append({"offer_id": item["offer_id"], "title": item["title"], "error": _http_error_detail(exc)})
        elif platform == "instagram" and mode == "reel_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    if publish_instagram_story_with_fallback(item, combined_item):
                        success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": _http_error_detail(exc),
                        }
                    )

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    deploy_stories_via_sftp(only_files=[reel_asset["filename"]])
                    created_reel = _create_instagram_reel_container_with_retry(
                        reel_asset["public_url"],
                        item["reel_payload"]["caption"],
                    )
                    status_payload = wait_for_instagram_container_ready(created_reel["result"]["id"])
                    published_reel = publish_instagram_container(created_reel["result"]["id"])
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url
                    combined_item["source_video_error"] = reel_asset_error
                    combined_item["instagram_reel_creation_id"] = created_reel["result"]["id"]
                    combined_item["instagram_reel_status"] = status_payload["result"]
                    combined_item["instagram_result"] = published_reel["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_reel",
                            "error": _http_error_detail(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        elif platform == "instagram" and mode == "feed_story":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    feed_filename = (item.get("instagram_payload", {}).get("image_filename") or "").strip()
                    if feed_filename:
                        deploy_stories_via_sftp(only_files=[feed_filename])
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
                            "error": _http_error_detail(exc),
                        }
                    )

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    if publish_instagram_story_with_fallback(item, combined_item):
                        success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": _http_error_detail(exc),
                        }
                    )

                if success_for_item:
                    items.append(combined_item)
        elif platform == "instagram" and mode == "feed_story_reel":
            for item in previews:
                combined_item = {
                    "offer_id": item["offer_id"],
                    "slug": item["slug"],
                    "title": item["title"],
                }
                success_for_item = False

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    feed_filename = (item.get("instagram_payload", {}).get("image_filename") or "").strip()
                    if feed_filename:
                        deploy_stories_via_sftp(only_files=[feed_filename])
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
                            "error": _http_error_detail(exc),
                        }
                    )

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    if publish_instagram_story_with_fallback(item, combined_item):
                        success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_story",
                            "error": _http_error_detail(exc),
                        }
                    )

                try:
                    if instagram_capacity_error:
                        raise ValueError(instagram_capacity_error)
                    reel_asset, reel_source, source_video_url, reel_asset_error = prepare_reel_asset(item)
                    deploy_stories_via_sftp(only_files=[reel_asset["filename"]])
                    created_reel = _create_instagram_reel_container_with_retry(
                        reel_asset["public_url"],
                        item["reel_payload"]["caption"],
                    )
                    status_payload = wait_for_instagram_container_ready(created_reel["result"]["id"])
                    published_reel = publish_instagram_container(created_reel["result"]["id"])
                    combined_item["reel_file"] = reel_asset["filename"]
                    combined_item["reel_source"] = reel_source
                    combined_item["source_video_url"] = source_video_url
                    combined_item["source_video_error"] = reel_asset_error
                    combined_item["instagram_reel_creation_id"] = created_reel["result"]["id"]
                    combined_item["instagram_reel_status"] = status_payload["result"]
                    combined_item["instagram_result"] = published_reel["result"]
                    success_for_item = True
                except Exception as exc:  # noqa: BLE001
                    errors.append(
                        {
                            "offer_id": item["offer_id"],
                            "title": item["title"],
                            "platform": "instagram_reel",
                            "error": _http_error_detail(exc),
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
            "warnings": warnings,
            "error_summary": (errors[0].get("error") if errors else ""),
            "warning_summary": (warnings[0].get("warning") if warnings else ""),
        }
        if items:
            result["asset_cleanup"] = _cleanup_generated_publish_assets()
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
    return HTMLResponse(
        index_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


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

    text_media_types = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".jsx": "text/babel; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml; charset=utf-8",
    }
    cache_headers = {"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    media_type = text_media_types.get(asset.suffix.lower())
    if media_type:
        return Response(content=asset.read_text(encoding="utf-8"), media_type=media_type, headers=cache_headers)

    return FileResponse(asset, headers=cache_headers)


@app.get("/dashboard/api/stories/{filename}")
def dashboard_story_asset(filename: str, _: str = Depends(require_manager_auth)):
    stories_dir = ensure_stories_dir().resolve()
    asset = (stories_dir / filename).resolve()
    try:
        asset.relative_to(stories_dir)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Story invalido.") from exc

    if not asset.exists() or not asset.is_file():
        raise HTTPException(status_code=404, detail="Story nao encontrado.")

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
    return execute_import_run(payload.providers, payload.limit, payload.keyword)


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


def _run_local_job_command(args: list[str], *, timeout_seconds: int = 3600) -> dict[str, Any]:
    runner_path = Path(__file__).resolve().parents[1] / "run_job.py"
    if not runner_path.is_file():
        raise ValueError("run_job.py nao encontrado no servidor do manager.")

    completed = subprocess.run(
        [sys.executable, str(runner_path), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=max(30, int(timeout_seconds or 3600)),
        cwd=str(runner_path.parent),
    )

    stdout_lines = [line.strip() for line in str(completed.stdout or "").splitlines() if line.strip()]
    payload: dict[str, Any] | None = None
    if stdout_lines:
        try:
            payload = json.loads(stdout_lines[-1])
        except json.JSONDecodeError:
            payload = None

    if completed.returncode != 0:
        if isinstance(payload, dict) and payload.get("error"):
            raise ValueError(str(payload.get("error") or "Falha ao executar job local."))
        stderr = str(completed.stderr or "").strip()
        stdout = str(completed.stdout or "").strip()
        raise ValueError(stderr or stdout or "Falha ao executar job local.")

    if not isinstance(payload, dict):
        raise ValueError("O job local nao retornou JSON valido.")
    if payload.get("ok") is False:
        raise ValueError(str(payload.get("error") or "O job local retornou erro."))
    return payload


def execute_youtube_cuts_analyze(url: str) -> dict[str, Any]:
    return analyze_youtube_video_for_cuts(url)


def _youtube_geo_blocked_error(exc: Exception | str) -> bool:
    message = str(exc or "").strip().lower()
    if not message:
        return False
    markers = (
        "bloqueio de pais no servidor",
        "not made this video available in your country",
        "not available in your country",
    )
    return any(marker in message for marker in markers)


def _youtube_geo_block_fallback_candidates(
    url: str,
    *,
    profile: dict[str, Any] | None,
    recent_limit: int = 12,
    videos_per_topic: int = 8,
    retry_candidates: int = 10,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    profile_id = int((profile or {}).get("id") or 0)
    if profile_id <= 0:
        return [], {}

    original_video_id = ""
    try:
        original_video_id = extract_youtube_video_id(url)
    except Exception:
        original_video_id = ""

    trends = execute_youtube_trends_themes(
        recent_limit=max(4, min(int(recent_limit or 12), 16)),
        videos_per_topic=max(4, min(int(videos_per_topic or 8), 10)),
        channel_profile_id=profile_id,
    )
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    max_candidates = max(1, min(int(retry_candidates or 10), 12))
    for item in trends.get("recent_uploads") or []:
        if not isinstance(item, dict):
            continue
        candidate_url = str(item.get("url") or "").strip()
        candidate_video_id = str(item.get("video_id") or "").strip()
        if not candidate_url or not candidate_video_id:
            continue
        if candidate_video_id == original_video_id or candidate_video_id in seen_ids:
            continue
        seen_ids.add(candidate_video_id)
        candidates.append(item)
        if len(candidates) >= max_candidates:
            break

    source_entries = _split_channel_sources((profile or {}).get("source_channels"))
    if len(candidates) < max_candidates and source_entries:
        try:
            access_token, ready_profile = _youtube_access_token_ready(profile_id)
            recent_uploads, _ = _fetch_recent_uploads_from_channel_list(
                access_token,
                source_entries=source_entries,
                recent_hours=168,
                uploads_per_channel=12,
                exclude_channel_id=str(ready_profile.get("channel_id") or ""),
            )
            detail_map = {
                str(item.get("video_id") or "").strip(): item
                for item in _videos_details(
                    access_token,
                    [
                        str(item.get("video_id") or "").strip()
                        for item in recent_uploads[:36]
                        if str(item.get("video_id") or "").strip()
                    ],
                )
            }
            for item in recent_uploads:
                candidate_video_id = str(item.get("video_id") or "").strip()
                if not candidate_video_id or candidate_video_id == original_video_id or candidate_video_id in seen_ids:
                    continue
                merged = detail_map.get(candidate_video_id, {}) | item
                candidate_url = str(merged.get("url") or f"https://www.youtube.com/watch?v={candidate_video_id}").strip()
                if not candidate_url:
                    continue
                seen_ids.add(candidate_video_id)
                candidates.append(
                    {
                        "video_id": candidate_video_id,
                        "url": candidate_url,
                        "title": str(merged.get("title") or ""),
                        "channel_title": str(merged.get("channel_title") or ""),
                        "published_at": str(merged.get("published_at") or ""),
                        "duration_seconds": int(merged.get("duration_seconds") or 0),
                        "source_type": str(merged.get("source_type") or "manual_channel_list"),
                    }
                )
                if len(candidates) >= max_candidates:
                    break
        except Exception:
            pass
    return candidates, trends


def _process_youtube_video_with_geo_fallback(
    url: str,
    *,
    limit: int,
    mode: str,
    selection_strategy: str,
    risk_profile: str,
    profile: dict[str, Any] | None,
    burn_subtitles: bool,
    retry_geo_block_with_profile_candidates: bool = True,
) -> dict[str, Any]:
    channel_profile_id = (profile or {}).get("id")
    channel_profile_name = (profile or {}).get("name")
    try:
        result = process_youtube_video_for_cuts(
            url,
            limit=limit,
            mode=mode,
            selection_strategy=selection_strategy,
            risk_profile=risk_profile,
            channel_profile_id=channel_profile_id,
            channel_profile_name=channel_profile_name,
            channel_preferences=profile or None,
            burn_subtitles=burn_subtitles,
        )
        result["source_fallback"] = {"used": False}
        return result
    except Exception as exc:
        if not retry_geo_block_with_profile_candidates or not _youtube_geo_blocked_error(exc):
            raise

        candidates, trends = _youtube_geo_block_fallback_candidates(url, profile=profile)
        if not candidates:
            raise ValueError(
                f"{str(exc)} Nao encontrei outro video recente elegivel para fallback no perfil "
                f"{str(channel_profile_name or '').strip() or 'selecionado'}."
            ) from exc

        fallback_errors: list[dict[str, Any]] = []
        for candidate in candidates:
            candidate_url = str(candidate.get("url") or "").strip()
            if not candidate_url:
                continue
            try:
                result = process_youtube_video_for_cuts(
                    candidate_url,
                    limit=limit,
                    mode=mode,
                    selection_strategy=selection_strategy,
                    risk_profile=risk_profile,
                    channel_profile_id=channel_profile_id,
                    channel_profile_name=channel_profile_name,
                    channel_preferences=profile or None,
                    burn_subtitles=burn_subtitles,
                )
                result["source_fallback"] = {
                    "used": True,
                    "reason": "geo_blocked_original",
                    "requested_url": url,
                    "processed_url": candidate_url,
                    "video_id": str(candidate.get("video_id") or ""),
                    "title": str(candidate.get("title") or ""),
                    "channel_title": str(candidate.get("channel_title") or ""),
                    "published_at": str(candidate.get("published_at") or ""),
                    "trend_profile": dict(trends.get("trend_profile") or {}),
                    "attempts": fallback_errors,
                }
                return result
            except Exception as fallback_exc:
                fallback_errors.append(
                    {
                        "url": candidate_url,
                        "video_id": str(candidate.get("video_id") or ""),
                        "title": str(candidate.get("title") or ""),
                        "error": str(fallback_exc),
                    }
                )

        last_error = fallback_errors[-1]["error"] if fallback_errors else ""
        raise ValueError(
            f"{str(exc)} Tambem falhei ao tentar outros videos recentes do perfil "
            f"{str(channel_profile_name or '').strip() or 'selecionado'}. "
            f"Ultimo erro: {last_error or 'sem detalhes'}"
        ) from exc


def execute_youtube_cuts_process(
    url: str,
    *,
    limit: int = 5,
    mode: str = "short",
    selection_strategy: str = "gemini_heuristica",
    risk_profile: str = "default",
    channel_profile_id: int | None = None,
    burn_subtitles: bool = True,
    retry_geo_block_with_profile_candidates: bool = True,
) -> dict[str, Any]:
    normalized_mode = (mode or "short").strip().lower()
    max_limit = 3 if normalized_mode == "long" else 8
    normalized_limit = max(1, min(int(limit or 5), max_limit))
    profile = None
    if channel_profile_id is not None:
        db = SessionLocal()
        try:
            profile = _resolve_youtube_channel_profile(db, channel_profile_id)
        finally:
            db.close()
    else:
        db = SessionLocal()
        try:
            profile = get_default_youtube_channel_profile(db)
        finally:
            db.close()

    result = _process_youtube_video_with_geo_fallback(
        url,
        limit=normalized_limit,
        mode=normalized_mode,
        selection_strategy=selection_strategy,
        risk_profile=risk_profile,
        profile=profile or None,
        burn_subtitles=burn_subtitles,
        retry_geo_block_with_profile_candidates=retry_geo_block_with_profile_candidates,
    )
    result["youtube_auth"] = _youtube_auth_snapshot(channel_profile_id or (profile or {}).get("id"), refresh=False)
    for item in result.get("cuts") or []:
        draft = build_youtube_cut_publish_draft(result["job_id"], int(item.get("cut_id") or 0))
        draft["channel_profile_id"] = (profile or {}).get("id")
        draft["channel_profile_name"] = (profile or {}).get("name") or ""
        item["publish_draft"] = draft
    return result


def execute_youtube_cut_private_test(
    url: str,
    *,
    limit: int = 3,
    selection_strategy: str = "gemini_heuristica",
    channel_profile_id: int | None = None,
    burn_subtitles: bool = True,
) -> dict[str, Any]:
    db = SessionLocal()
    try:
        profile = _resolve_youtube_channel_profile(db, channel_profile_id) if channel_profile_id is not None else get_default_youtube_channel_profile(db)
    finally:
        db.close()

    process_result = execute_youtube_cuts_process(
        url,
        limit=max(1, min(int(limit or 3), 4)),
        mode="short",
        selection_strategy=selection_strategy,
        risk_profile="conservative",
        channel_profile_id=channel_profile_id or (profile or {}).get("id"),
        burn_subtitles=burn_subtitles,
        retry_geo_block_with_profile_candidates=True,
    )
    processed_cuts = list(process_result.get("cuts") or [])
    requires_person_gate = _youtube_profile_requires_person_gate(profile)
    if requires_person_gate and processed_cuts and not any(bool(item.get("publish_allowed", True)) for item in processed_cuts if isinstance(item, dict)):
        processed_cuts = _try_left_framing_for_blocked_youtube_cuts(str(process_result.get("job_id") or ""), processed_cuts)
        process_result["cuts"] = processed_cuts

    selected_cut = _best_generated_youtube_cut(processed_cuts, require_person_gate=requires_person_gate)
    publish_result = execute_youtube_cut_publish(
        job_id=str(process_result.get("job_id") or ""),
        cut_id=int(selected_cut.get("cut_id") or 0),
        privacy_status="private",
        mode="short",
        channel_profile_id=channel_profile_id or (profile or {}).get("id"),
    )
    return {
        "ok": True,
        "risk_profile": "conservative",
        "channel_profile_id": (profile or {}).get("id"),
        "channel_profile_name": (profile or {}).get("name") or "",
        "job_id": str(process_result.get("job_id") or ""),
        "selected_cut": {
            "cut_id": int(selected_cut.get("cut_id") or 0),
            "title": str(selected_cut.get("copy_title") or selected_cut.get("title") or ""),
            "duration_seconds": float(selected_cut.get("duration_seconds") or 0.0),
            "score": int(selected_cut.get("score") or 0),
            "publish_allowed": bool(selected_cut.get("publish_allowed", True)),
            "risk_notes": list(selected_cut.get("risk_notes") or []),
        },
        "process_result": process_result,
        "publish_result": publish_result,
    }


def execute_youtube_cut_publish(
    *,
    job_id: str,
    cut_id: int,
    title: str | None = None,
    description: str | None = None,
    privacy_status: str = "public",
    publish_at: str | None = None,
    mode: str = "short",
    channel_profile_id: int | None = None,
) -> dict[str, Any]:
    draft = build_youtube_cut_publish_draft(job_id, cut_id, privacy_status=privacy_status)
    normalized_title = (title or draft["title"]).strip()
    normalized_description = (description or draft["description"]).strip()
    normalized_privacy = (privacy_status or draft["privacy_status"]).strip().lower()
    normalized_publish_at = (publish_at or "").strip()
    normalized_mode = (mode or draft.get("mode") or "short").strip().lower()
    access_token, profile = _youtube_access_token_ready(channel_profile_id or draft.get("channel_profile_id"))
    mismatch_error = _youtube_profile_channel_mismatch(profile)
    if mismatch_error:
        raise ValueError(mismatch_error)
    if normalized_mode == "short" and _youtube_profile_requires_person_gate(profile) and not bool(draft.get("publish_allowed", True)):
        raise ValueError(str(draft.get("publish_block_reason") or "Esse short nao mostrou uma pessoa falando no enquadramento inicial."))
    video_path = youtube_cut_video_path(job_id, cut_id)
    published = upload_youtube_short(
        access_token,
        video_path,
        title=normalized_title,
        description=normalized_description,
        privacy_status=normalized_privacy,
        publish_at=normalized_publish_at or None,
    )
    video_id = str(published.get("id") or "").strip()
    thumbnail_result = None
    thumbnail_error = ""
    thumbnail_filename = str(draft.get("thumbnail_filename") or "").strip()
    if normalized_mode == "long" and video_id and thumbnail_filename:
        try:
            thumbnail_path = youtube_cuts_asset_path(job_id, thumbnail_filename)
            thumbnail_result = upload_youtube_thumbnail(access_token, video_id, thumbnail_path)
        except Exception as exc:  # noqa: BLE001
            thumbnail_error = str(exc)
    return {
        "ok": True,
        "job_id": job_id,
        "cut_id": int(cut_id),
        "mode": normalized_mode,
        "channel_profile_id": int(profile["id"]),
        "channel_profile_name": profile["name"],
        "privacy_status": normalized_privacy,
        "publish_at": str(published.get("publishAt") or normalized_publish_at or ""),
        "youtube_video_id": video_id,
        "youtube_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
        "thumbnail_result": thumbnail_result,
        "thumbnail_error": thumbnail_error,
        "result": published,
    }


def execute_youtube_trends_themes(
    *,
    recent_limit: int = 4,
    videos_per_topic: int = 4,
    channel_profile_id: int | None = None,
) -> dict[str, Any]:
    access_token, profile = _youtube_access_token_ready(channel_profile_id)
    result = build_channel_trend_ideas(
        access_token,
        recent_limit=max(1, min(int(recent_limit or 4), 16)),
        videos_per_topic=max(1, min(int(videos_per_topic or 4), 10)),
        channel_profile_name=str(profile.get("name") or ""),
        channel_preferences=profile,
    )
    result["target_profile"] = {
        "id": int(profile["id"]),
        "name": profile["name"],
        "handle": profile.get("handle") or "",
        "channel_title": profile.get("channel_title") or "",
        "channel_custom_url": profile.get("channel_custom_url") or "",
    }
    return result


def _youtube_auto_cut_recent_source_ids(db, *, channel_profile_id: int, lookback_days: int = 14) -> set[str]:
    rows = db.execute(
        text(
            """
            SELECT payload_json, result_json
            FROM automacao_execucoes
            WHERE tipo = 'youtube_auto_cut'
              AND status = 'success'
              AND criado_em >= (NOW() - INTERVAL :lookback_days DAY)
            ORDER BY criado_em DESC, id DESC
            LIMIT 120
            """
        ),
        {"lookback_days": max(1, int(lookback_days or 14))},
    ).mappings().all()

    used_ids: set[str] = set()
    for row in rows:
        for column in ("result_json", "payload_json"):
            payload = row.get(column)
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = None
            if not isinstance(payload, dict):
                continue
            payload_profile_id = int(
                payload.get("channel_profile_id")
                or ((payload.get("target_profile") or {}).get("id") if isinstance(payload.get("target_profile"), dict) else 0)
                or 0
            )
            if payload_profile_id != int(channel_profile_id):
                continue
            source_video_id = str(
                payload.get("source_video_id")
                or ((payload.get("selected_source") or {}).get("video_id") if isinstance(payload.get("selected_source"), dict) else "")
                or ""
            ).strip()
            if source_video_id:
                used_ids.add(source_video_id)
    return used_ids


def _compact_youtube_profile_identity(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())


def _youtube_profile_requires_person_gate(profile: dict[str, Any] | None) -> bool:
    if not isinstance(profile, dict):
        return False
    identities = [
        profile.get("handle"),
        profile.get("channel_custom_url"),
        profile.get("name"),
        profile.get("channel_title"),
    ]
    compact_values = {
        _compact_youtube_profile_identity(item)
        for item in identities
        if str(item or "").strip()
    }
    if "zerocortespolitica" in compact_values:
        return False
    return False


def _youtube_profile_channel_mismatch(profile: dict[str, Any] | None) -> str:
    if not isinstance(profile, dict):
        return ""
    expected = _compact_youtube_profile_identity(profile.get("handle"))
    actual = _compact_youtube_profile_identity(profile.get("channel_custom_url"))
    if not expected or not actual:
        return ""
    if expected == actual:
        return ""
    return (
        "O perfil selecionado esta autenticado no canal errado. "
        f"Perfil espera @{str(profile.get('handle') or '').lstrip('@')}, "
        f"mas o OAuth salvo aponta para @{str(profile.get('channel_custom_url') or '').lstrip('@')}. "
        'Use "Reconectar YouTube" nesse perfil antes de publicar.'
    )


def _best_generated_youtube_cut(cuts: list[dict[str, Any]], *, require_person_gate: bool = True) -> dict[str, Any]:
    available = [item for item in cuts if isinstance(item, dict)]
    if not available:
        raise ValueError("Nenhum corte foi gerado para publicar automaticamente.")
    if require_person_gate:
        publishable = [item for item in available if bool(item.get("publish_allowed", True))]
        if publishable:
            available = publishable
        else:
            raise ValueError("Nenhum corte gerado mostrou uma pessoa em quadro no inicio. Ajuste o enquadramento antes de publicar.")
    return max(
        available,
        key=lambda item: (
            int(((item.get("scorecard") or {}).get("overall")) or item.get("score") or 0),
            float(item.get("duration_seconds") or 0),
        ),
    )


def _try_left_framing_for_blocked_youtube_cuts(job_id: str, cuts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refreshed: list[dict[str, Any]] = []
    for item in [cut for cut in cuts if isinstance(cut, dict)]:
        updated_item = dict(item)
        if bool(updated_item.get("publish_allowed", True)):
            refreshed.append(updated_item)
            continue

        current_zone = str(updated_item.get("opening_focus_zone") or updated_item.get("crop_override") or "").strip().lower()
        if current_zone == "esquerda" and bool(updated_item.get("opening_speaker_detected")):
            refreshed.append(updated_item)
            continue

        cut_id = int(updated_item.get("cut_id") or 0)
        if cut_id <= 0 or not str(job_id or "").strip():
            refreshed.append(updated_item)
            continue

        try:
            rerendered = rerender_youtube_cut(str(job_id), cut_id, framing="esquerda")
        except Exception:
            refreshed.append(updated_item)
            continue

        updated_item["crop_override"] = str(rerendered.get("framing") or "esquerda")
        updated_item["opening_focus_zone"] = str(rerendered.get("opening_focus_zone") or "esquerda")
        updated_item["opening_focus_confidence"] = int(rerendered.get("opening_focus_confidence") or updated_item.get("opening_focus_confidence") or 0)
        updated_item["opening_subject_signal"] = str(rerendered.get("opening_subject_signal") or updated_item.get("opening_subject_signal") or "")
        updated_item["opening_visual_score"] = int(rerendered.get("opening_visual_score") or updated_item.get("opening_visual_score") or 0)
        updated_item["opening_speaker_detected"] = bool(rerendered.get("opening_speaker_detected"))
        updated_item["opening_speaker_score"] = int(rerendered.get("opening_speaker_score") or updated_item.get("opening_speaker_score") or 0)
        updated_item["publish_allowed"] = bool(rerendered.get("publish_allowed"))
        updated_item["publish_block_reason"] = str(rerendered.get("publish_block_reason") or updated_item.get("publish_block_reason") or "")
        updated_item["video_filename"] = str(rerendered.get("video_filename") or updated_item.get("video_filename") or "")
        refreshed.append(updated_item)
    return refreshed


def execute_youtube_auto_cut_publish(
    *,
    channel_profile_id: int | None = None,
    channel_profile_name: str | None = None,
    recent_limit: int = 8,
    videos_per_topic: int = 5,
    cut_limit: int = 5,
    retry_candidates: int = 4,
    lookback_days: int = 14,
    selection_strategy: str = "openai_heuristica",
) -> dict[str, Any]:
    db = SessionLocal()
    run_id = 0
    execution_result: dict[str, Any] | None = None
    try:
        profile = (
            _resolve_youtube_channel_profile(db, channel_profile_id)
            if channel_profile_id
            else _resolve_youtube_channel_profile_by_name(db, channel_profile_name)
            if channel_profile_name
            else _resolve_youtube_channel_profile(db)
        )
        profile_id = int(profile["id"])
        requires_person_gate = _youtube_profile_requires_person_gate(profile)
        payload = {
            "channel_profile_id": profile_id,
            "channel_profile_name": profile.get("name") or "",
            "recent_limit": int(recent_limit or 8),
            "videos_per_topic": int(videos_per_topic or 5),
            "cut_limit": int(cut_limit or 5),
            "retry_candidates": int(retry_candidates or 4),
            "lookback_days": int(lookback_days or 14),
            "selection_strategy": selection_strategy,
        }
        run_id = record_execution_start(
            db,
            tipo="youtube_auto_cut",
            provider="youtube",
            canal=str(profile.get("name") or ""),
            modo="short",
            requested_count=1,
            payload=payload,
        )

        trends = execute_youtube_trends_themes(
            recent_limit=max(1, min(int(recent_limit or 8), 16)),
            videos_per_topic=max(1, min(int(videos_per_topic or 5), 10)),
            channel_profile_id=profile_id,
        )
        all_candidates = [item for item in (trends.get("recent_uploads") or []) if isinstance(item, dict) and str(item.get("url") or "").strip()]
        if not all_candidates:
            raise ValueError("O radar nao retornou videos candidatos para o corte automatico.")

        recent_source_ids = _youtube_auto_cut_recent_source_ids(db, channel_profile_id=profile_id, lookback_days=lookback_days)
        candidates = [item for item in all_candidates if str(item.get("video_id") or "").strip() not in recent_source_ids]
        reused_source_fallback = False
        if not candidates:
            candidates = all_candidates
            reused_source_fallback = True

        attempts: list[dict[str, Any]] = []
        max_attempts = max(1, min(max(int(retry_candidates or 8), 12), len(candidates)))
        for candidate in candidates[:max_attempts]:
            source_video_id = str(candidate.get("video_id") or "").strip()
            source_duration_seconds = int(candidate.get("duration_seconds") or 0)
            requested_burn_subtitles = True
            attempt_payload = {
                "video_id": source_video_id,
                "title": str(candidate.get("title") or ""),
                "url": str(candidate.get("url") or ""),
                "duration_seconds": source_duration_seconds,
                "burn_subtitles_requested": requested_burn_subtitles,
                "cut_score": int(candidate.get("cut_score") or 0),
            }
            try:
                process_result = execute_youtube_cuts_process(
                    str(candidate.get("url") or ""),
                    limit=max(1, min(int(cut_limit or 5), 8)),
                    mode="short",
                    selection_strategy=selection_strategy,
                    channel_profile_id=profile_id,
                    burn_subtitles=requested_burn_subtitles,
                    retry_geo_block_with_profile_candidates=False,
                )
                processed_cuts = list(process_result.get("cuts") or [])
                if requires_person_gate and processed_cuts and not any(bool(item.get("publish_allowed", True)) for item in processed_cuts if isinstance(item, dict)):
                    processed_cuts = _try_left_framing_for_blocked_youtube_cuts(str(process_result.get("job_id") or ""), processed_cuts)
                    process_result["cuts"] = processed_cuts
                selected_cut = _best_generated_youtube_cut(processed_cuts, require_person_gate=requires_person_gate)
                actual_burn_subtitles = bool(process_result.get("burn_subtitles"))
                publish_result = execute_youtube_cut_publish(
                    job_id=str(process_result.get("job_id") or ""),
                    cut_id=int(selected_cut.get("cut_id") or 0),
                    privacy_status="public",
                    mode="short",
                    channel_profile_id=profile_id,
                )
                execution_result = {
                    "ok": True,
                    "channel_profile_id": profile_id,
                    "channel_profile_name": profile.get("name") or "",
                    "used_recent_source_fallback": reused_source_fallback,
                    "source_video_id": source_video_id,
                    "selected_source": {
                        **attempt_payload,
                        "channel_title": str(candidate.get("channel_title") or ""),
                        "published_at": str(candidate.get("published_at") or ""),
                    },
                    "selected_cut": {
                        "cut_id": int(selected_cut.get("cut_id") or 0),
                        "title": str(selected_cut.get("title") or ""),
                        "hook": str(selected_cut.get("hook") or ""),
                        "score": int(((selected_cut.get("scorecard") or {}).get("overall")) or selected_cut.get("score") or 0),
                        "duration_seconds": float(selected_cut.get("duration_seconds") or 0),
                        "duration_label": str(selected_cut.get("duration_label") or ""),
                        "burn_subtitles": actual_burn_subtitles,
                        "crop_override": str(selected_cut.get("crop_override") or "auto"),
                        "opening_focus_zone": str(selected_cut.get("opening_focus_zone") or ""),
                        "opening_speaker_detected": bool(selected_cut.get("opening_speaker_detected")),
                        "opening_speaker_score": int(selected_cut.get("opening_speaker_score") or 0),
                    },
                    "job_id": str(process_result.get("job_id") or ""),
                    "youtube_video_id": str(publish_result.get("youtube_video_id") or ""),
                    "youtube_url": str(publish_result.get("youtube_url") or ""),
                    "privacy_status": "public",
                    "radar_profile": dict(trends.get("trend_profile") or {}),
                    "subtitle_decision": process_result.get("subtitle_decision") or {},
                    "attempts": attempts + [{"ok": True, **attempt_payload}],
                }
                record_execution_success(db, run_id, processed_count=1, result=execution_result)
                return execution_result
            except Exception as exc:  # noqa: BLE001
                attempts.append({"ok": False, **attempt_payload, "error": str(exc)})

        error_result = {
            "ok": False,
            "channel_profile_id": profile_id,
            "channel_profile_name": profile.get("name") or "",
            "used_recent_source_fallback": reused_source_fallback,
            "radar_profile": dict(trends.get("trend_profile") or {}),
            "attempts": attempts,
        }
        error_message = "Nao consegui gerar e publicar automaticamente um corte a partir dos videos do radar."
        record_execution_error(db, run_id, error_message=error_message, result=error_result)
        raise ValueError(error_message)
    except Exception as exc:
        if run_id and execution_result is None:
            try:
                record_execution_error(db, run_id, error_message=str(exc))
            except Exception:
                pass
        raise
    finally:
        db.close()


@app.get("/dashboard/api/growth/radar")
def dashboard_api_growth_radar(_: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        return {"ok": True, **fetch_growth_radar(db)}
    finally:
        db.close()


@app.post("/dashboard/api/growth/targets")
def dashboard_api_growth_target_create(payload: DashboardGrowthTargetPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        normalized = _normalize_growth_target_payload(payload)
        target = create_growth_target(db, normalized)
        return {"ok": True, "target": target}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/growth/targets/{target_id}")
def dashboard_api_growth_target_update(target_id: int, payload: DashboardGrowthTargetPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        normalized = _normalize_growth_target_payload(payload)
        target = update_growth_target(db, target_id, normalized)
        return {"ok": True, "target": target}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.delete("/dashboard/api/growth/targets/{target_id}")
def dashboard_api_growth_target_delete(target_id: int, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        delete_growth_target(db, target_id)
        return {"ok": True, "deleted_id": int(target_id)}
    finally:
        db.close()


@app.get("/dashboard/api/offers")
def dashboard_api_offers(q: str = "", limit: int = 10, page: int = 1, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        ensure_dashboard_tables(db)
        if _purge_zero_price_offers(db):
            db.commit()
        normalized_limit = min(max(int(limit or 10), 1), 50)
        normalized_page = max(int(page or 1), 1)
        query = (q or "").strip()
        params: dict[str, Any] = {"limit": normalized_limit, "offset": 0}
        where_sql = ""
        if query:
            where_sql = """
            WHERE titulo LIKE :query
               OR slug LIKE :query
               OR loja LIKE :query
               OR categoria LIKE :query
               OR tags LIKE :query
            """
            params["query"] = f"%{query}%"
        total = int(
            db.execute(
                text(f"SELECT COUNT(*) FROM ofertas {where_sql}"),
                {key: value for key, value in params.items() if key == "query"},
            ).scalar()
            or 0
        )
        pages = max(1, (total + normalized_limit - 1) // normalized_limit)
        normalized_page = min(normalized_page, pages)
        params["offset"] = (normalized_page - 1) * normalized_limit
        sql = f"""
            SELECT
              id,
              slug,
              titulo,
              descricao,
              preco,
              preco_antigo,
              desconto_percentual,
              preco_pix,
              preco_outros_meios,
              parcelas_texto,
              frete_texto,
              avaliacao_nota,
              avaliacao_total,
              promocao_texto,
              loja,
              url_afiliado,
              cupom,
              imagem_url,
              imagem_urls_json,
              video_urls_json,
              categoria,
              tags,
              destaque,
              ativo,
              expira_em,
              atualizado_em
            FROM ofertas
            {where_sql}
            ORDER BY atualizado_em DESC, id DESC
            LIMIT :limit OFFSET :offset
        """
        rows = db.execute(text(sql), params).mappings().all()
        items = [
            {
                **dict(row),
                "preco": float(row["preco"] or 0),
                "preco_antigo": float(row["preco_antigo"]) if row["preco_antigo"] is not None else None,
                "desconto_percentual": int(row["desconto_percentual"]) if row["desconto_percentual"] is not None else None,
                "preco_pix": float(row["preco_pix"]) if row["preco_pix"] is not None else None,
                "preco_outros_meios": float(row["preco_outros_meios"]) if row["preco_outros_meios"] is not None else None,
                "avaliacao_nota": float(row["avaliacao_nota"]) if row["avaliacao_nota"] is not None else None,
                "avaliacao_total": int(row["avaliacao_total"]) if row["avaliacao_total"] is not None else None,
                "destaque": bool(row["destaque"]),
                "ativo": bool(row["ativo"]),
                "imagem_urls": _decode_json_url_list(row["imagem_urls_json"]),
                "video_urls": _decode_json_url_list(row["video_urls_json"]),
                "offer_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}",
                "store_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}&go=1",
            }
            for row in rows
        ]
        return {
            "count": len(items),
            "total": total,
            "page": normalized_page,
            "pages": pages,
            "limit": normalized_limit,
            "items": items,
        }
    finally:
        db.close()


@app.post("/dashboard/api/offers/{offer_id}")
def dashboard_api_offer_update(offer_id: int, payload: DashboardOfferUpdatePayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        ensure_dashboard_tables(db)
        existing = db.execute(text("SELECT id FROM ofertas WHERE id = :id LIMIT 1"), {"id": offer_id}).scalar()
        if not existing:
            raise HTTPException(status_code=404, detail="Oferta nao encontrada.")

        title = (payload.titulo or "").strip()
        affiliate_url = (payload.url_afiliado or "").strip()
        if not title or not affiliate_url:
            raise HTTPException(status_code=400, detail="Titulo e URL afiliado sao obrigatorios.")
        if _price_is_zero_or_less(payload.preco):
            return {"ok": True, "ignored": True, "reason": "zero_price", "offer_id": offer_id}

        slug = _normalize_offer_slug(db, payload.slug, title, ignore_id=offer_id)
        old_price = _parse_decimal(payload.preco_antigo, default=0.0) if payload.preco_antigo not in (None, "") else None
        discount_percent = int(_parse_decimal(payload.desconto_percentual, default=0.0)) if payload.desconto_percentual not in (None, "") else None
        pix_price = _parse_decimal(payload.preco_pix, default=0.0) if payload.preco_pix not in (None, "") else None
        other_price = _parse_decimal(payload.preco_outros_meios, default=0.0) if payload.preco_outros_meios not in (None, "") else None
        rating = _parse_decimal(payload.avaliacao_nota, default=0.0) if payload.avaliacao_nota not in (None, "") else None
        rating_count = int(_parse_decimal(payload.avaliacao_total, default=0.0)) if payload.avaliacao_total not in (None, "") else None
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
                    desconto_percentual = :desconto_percentual,
                    preco_pix = :preco_pix,
                    preco_outros_meios = :preco_outros_meios,
                    parcelas_texto = :parcelas_texto,
                    frete_texto = :frete_texto,
                    avaliacao_nota = :avaliacao_nota,
                    avaliacao_total = :avaliacao_total,
                    promocao_texto = :promocao_texto,
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
                "desconto_percentual": discount_percent,
                "preco_pix": pix_price,
                "preco_outros_meios": other_price,
                "parcelas_texto": (payload.parcelas_texto or "").strip() or None,
                "frete_texto": (payload.frete_texto or "").strip() or None,
                "avaliacao_nota": rating,
                "avaliacao_total": rating_count,
                "promocao_texto": (payload.promocao_texto or "").strip() or None,
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
                  desconto_percentual,
                  preco_pix,
                  preco_outros_meios,
                  parcelas_texto,
                  frete_texto,
                  avaliacao_nota,
                  avaliacao_total,
                  promocao_texto,
                  loja,
                  url_afiliado,
                  cupom,
                  imagem_url,
                  imagem_urls_json,
                  video_urls_json,
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
            "desconto_percentual": int(row["desconto_percentual"]) if row["desconto_percentual"] is not None else None,
            "preco_pix": float(row["preco_pix"]) if row["preco_pix"] is not None else None,
            "preco_outros_meios": float(row["preco_outros_meios"]) if row["preco_outros_meios"] is not None else None,
            "avaliacao_nota": float(row["avaliacao_nota"]) if row["avaliacao_nota"] is not None else None,
            "avaliacao_total": int(row["avaliacao_total"]) if row["avaliacao_total"] is not None else None,
            "destaque": bool(row["destaque"]),
            "ativo": bool(row["ativo"]),
            "imagem_urls": _decode_json_url_list(row["imagem_urls_json"]),
            "video_urls": _decode_json_url_list(row["video_urls_json"]),
            "offer_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}",
            "store_url": f"{_site_base_url()}/oferta.php?slug={row['slug']}&go=1",
        }
        return {"ok": True, "item": item}
    finally:
        db.close()


def execute_deploy_automation() -> dict:
    db = SessionLocal()
    run_id = record_execution_start(
        db,
        tipo="deploy",
        canal="sftp",
        modo="automacao_ofertas",
        requested_count=0,
        payload={"target": "automacao_ofertas"},
    )
    try:
        result = deploy_automation_backend_via_sftp()
        record_execution_success(db, run_id, processed_count=int(result.get("count") or 0), result=result)
        return {"run_id": run_id} | result
    except Exception as exc:  # noqa: BLE001
        record_execution_error(db, run_id, error_message=str(exc))
        raise
    finally:
        db.close()


@app.delete("/dashboard/api/offers/{offer_id}")
def dashboard_api_offer_delete(offer_id: int, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        row = db.execute(
            text("SELECT id, slug, titulo FROM ofertas WHERE id = :id LIMIT 1"),
            {"id": offer_id},
        ).mappings().first()
        if not row:
            raise HTTPException(status_code=404, detail="Oferta nao encontrada.")

        db.execute(text("DELETE FROM cliques WHERE oferta_id = :id"), {"id": offer_id})
        db.execute(text("DELETE FROM ofertas WHERE id = :id"), {"id": offer_id})
        db.commit()
        return {
            "ok": True,
            "deleted": {
                "id": int(row["id"]),
                "slug": str(row["slug"] or ""),
                "titulo": str(row["titulo"] or ""),
            },
        }
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


@app.post("/dashboard/api/import/store/shopee/reimport-without-video")
def dashboard_api_shopee_reimport_without_video(payload: DashboardShopeeReimportPayload, _: str = Depends(require_manager_auth)):
    normalized_limit = None if payload.limit in (None, "", 0) else max(1, min(int(payload.limit), 1000))
    command_args = [
        "refresh-existing-offers",
        "--store",
        "shopee",
        "--shopee-video-state",
        "without",
        "--max-images",
        "5",
    ]
    if normalized_limit is not None:
        command_args.extend(["--limit", str(normalized_limit)])
    try:
        command_result = _run_local_job_command(
            command_args,
            timeout_seconds=max(3600, (normalized_limit or 500) * 90),
        )
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail=f"O job da Shopee excedeu o tempo de espera do manager ({int(exc.timeout)}s).")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))

    result = command_result.get("result") if isinstance(command_result.get("result"), dict) else {}
    return {
        "ok": True,
        "store": "Shopee",
        "queue": "without_video",
        "limit_requested": normalized_limit,
        **result,
    }


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
            raw = item.model_dump()
            raw.update(
                {
                    "title": item.title,
                    "description": item.description or "",
                    "url": item.url or item.canonical_url or "",
                    "canonical_url": item.canonical_url or item.url or "",
                    "image": item.image or "",
                    "image_urls": item.image_urls or ([item.image] if item.image else []),
                    "category": item.category or "ofertas",
                    "coupon": item.coupon or None,
                    "tags": item.tags or f"{(item.provider or 'manual').strip().lower()},manual",
                    "featured": int(item.featured or 0),
                    "affiliate_tag": item.affiliate_code or "",
                    "video_url": item.video_url or "",
                    "video_urls": item.video_urls or ([item.video_url] if item.video_url else []),
                }
            )
            processed_items.append(raw | {"store": store})

        summary = {"processed": 0, "created": 0, "updated": 0, "skipped": 0}
        imported: list[dict[str, Any]] = []
        for item in processed_items:
            normalized = normalize_offer(item, item["store"], item.get("affiliate_tag"))
            action = publish_offer(db, normalized)
            summary["processed"] += 1
            summary[action] += 1
            if action == "skipped":
                continue
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
            "skipped": summary["skipped"],
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


@app.post("/dashboard/api/youtube/cuts/analyze")
def dashboard_api_youtube_cuts_analyze(payload: DashboardYoutubeCutsAnalyzePayload, _: str = Depends(require_manager_auth)):
    try:
        return analyze_youtube_video_for_cuts(payload.url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar metadados do YouTube: {e}")


@app.post("/dashboard/api/youtube/cuts/process")
def dashboard_api_youtube_cuts_process(payload: DashboardYoutubeCutsProcessPayload, _: str = Depends(require_manager_auth)):
    try:
        mode = (payload.mode or "short").strip().lower()
        max_limit = 3 if mode == "long" else 8
        limit = max(1, min(int(payload.limit or 5), max_limit))
        profile = None
        if payload.channel_profile_id is not None:
            db = SessionLocal()
            try:
                profile = _resolve_youtube_channel_profile(db, payload.channel_profile_id)
            finally:
                db.close()
        else:
            db = SessionLocal()
            try:
                profile = get_default_youtube_channel_profile(db)
            finally:
                db.close()
        result = execute_youtube_cuts_process(
            payload.url,
            limit=limit,
            mode=mode,
            selection_strategy=payload.selection_strategy,
            risk_profile=payload.risk_profile,
            channel_profile_id=payload.channel_profile_id or (profile or {}).get("id"),
            burn_subtitles=payload.burn_subtitles,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar YouTube: {e}")


@app.get("/dashboard/api/youtube/channels")
def dashboard_api_youtube_channels(_: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        profiles = fetch_youtube_channel_profiles(db)
        return {"ok": True, "profiles": [_youtube_channel_public_profile(item) for item in profiles]}
    finally:
        db.close()


@app.post("/dashboard/api/import/store/mercadolivre/repair-product-links")
def dashboard_api_mercadolivre_repair_product_links(payload: DashboardAmazonRepairPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        summary = repair_mercadolivre_product_links(db, only_inactive=bool(payload.only_inactive))
        db.commit()
        return {"ok": True, "store": "Mercado Livre", **summary}
    except ValueError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/youtube/channels")
def dashboard_api_youtube_channel_create(payload: DashboardYoutubeChannelPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        profile = create_youtube_channel_profile(db, _youtube_channel_profile_payload(payload))
        return {"ok": True, "profile": _youtube_channel_public_profile(profile)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.post("/dashboard/api/youtube/channels/{profile_id}")
def dashboard_api_youtube_channel_update(profile_id: int, payload: DashboardYoutubeChannelPayload, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        current = get_youtube_channel_profile(db, profile_id)
        profile = update_youtube_channel_profile(db, profile_id, _youtube_channel_profile_payload(payload, current=current))
        return {"ok": True, "profile": _youtube_channel_public_profile(profile)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.delete("/dashboard/api/youtube/channels/{profile_id}")
def dashboard_api_youtube_channel_delete(profile_id: int, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        deleted = delete_youtube_channel_profile(db, profile_id)
        return {"ok": True, "deleted": _youtube_channel_public_profile(deleted)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    finally:
        db.close()


@app.get("/dashboard/api/youtube/oauth/status")
def dashboard_api_youtube_oauth_status(channel_profile_id: int | None = None, _: str = Depends(require_manager_auth)):
    try:
        return {"ok": True, "youtube_auth": _youtube_auth_snapshot(channel_profile_id, refresh=True)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha ao consultar autenticacao do YouTube: {e}")


@app.get("/dashboard/api/youtube/oauth/url")
def dashboard_api_youtube_oauth_url(channel_profile_id: int | None = None, _: str = Depends(require_manager_auth)):
    db = SessionLocal()
    try:
        profile = _resolve_youtube_channel_profile(db, channel_profile_id)
        state = secrets.token_hex(16)
        update_youtube_channel_profile(db, int(profile["id"]), {"oauth_state": state})
        return {
            "ok": True,
            "channel_profile_id": int(profile["id"]),
            "channel_profile_name": profile["name"],
            **build_youtube_auth_url(
                state,
                client_id=str(profile.get("client_id") or ""),
                redirect_uri=str(profile.get("redirect_uri") or ""),
            ),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        db.close()


@app.get("/dashboard/api/youtube/trends/themes")
def dashboard_api_youtube_trends_themes(
    recent_limit: int = 4,
    videos_per_topic: int = 4,
    channel_profile_id: int | None = None,
    _: str = Depends(require_manager_auth),
):
    try:
        access_token, profile = _youtube_access_token_ready(channel_profile_id)
        result = build_channel_trend_ideas(
            access_token,
            recent_limit=max(1, min(int(recent_limit or 4), 16)),
            videos_per_topic=max(1, min(int(videos_per_topic or 4), 10)),
            channel_profile_name=str(profile.get("name") or ""),
            channel_preferences=profile,
        )
        result["target_profile"] = {
            "id": int(profile["id"]),
            "name": profile["name"],
            "handle": profile.get("handle") or "",
            "channel_title": profile.get("channel_title") or "",
            "channel_custom_url": profile.get("channel_custom_url") or "",
        }
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha ao buscar videos em alta no YouTube: {e}")


@app.post("/dashboard/api/youtube/cuts/publish")
def dashboard_api_youtube_cuts_publish(payload: DashboardYoutubeCutPublishPayload, _: str = Depends(require_manager_auth)):
    try:
        draft = build_youtube_cut_publish_draft(payload.job_id, payload.cut_id, privacy_status=payload.privacy_status)
        title = (payload.title or draft["title"]).strip()
        description = (payload.description or draft["description"]).strip()
        privacy_status = (payload.privacy_status or draft["privacy_status"]).strip().lower()
        publish_at = (payload.publish_at or "").strip()
        mode = (payload.mode or draft.get("mode") or "short").strip().lower()
        if mode == "short" and not bool(draft.get("publish_allowed", True)):
            raise ValueError(str(draft.get("publish_block_reason") or "Esse short nao mostrou uma pessoa falando no enquadramento inicial."))
        access_token, profile = _youtube_access_token_ready(payload.channel_profile_id or draft.get("channel_profile_id"))
        video_path = youtube_cut_video_path(payload.job_id, payload.cut_id)
        published = upload_youtube_short(
            access_token,
            video_path,
            title=title,
            description=description,
            privacy_status=privacy_status,
            publish_at=publish_at or None,
        )
        video_id = str(published.get("id") or "").strip()
        thumbnail_result = None
        thumbnail_error = ""
        thumbnail_filename = str(draft.get("thumbnail_filename") or "").strip()
        if mode == "long" and video_id and thumbnail_filename:
            try:
                thumbnail_path = youtube_cuts_asset_path(payload.job_id, thumbnail_filename)
                thumbnail_result = upload_youtube_thumbnail(access_token, video_id, thumbnail_path)
            except Exception as exc:  # noqa: BLE001
                thumbnail_error = str(exc)
        return {
            "ok": True,
            "job_id": payload.job_id,
            "cut_id": payload.cut_id,
            "mode": mode,
            "channel_profile_id": int(profile["id"]),
            "channel_profile_name": profile["name"],
            "privacy_status": privacy_status,
            "publish_at": str(published.get("publishAt") or publish_at or ""),
            "youtube_video_id": video_id,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else "",
            "thumbnail_result": thumbnail_result,
            "thumbnail_error": thumbnail_error,
            "result": published,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha ao publicar no YouTube: {e}")


@app.get("/dashboard/api/youtube/cuts/assets/{job_id}/{filename}")
def dashboard_api_youtube_cuts_asset(job_id: str, filename: str, _: str = Depends(require_manager_auth)):
    try:
        return FileResponse(youtube_cuts_asset_path(job_id, filename))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/dashboard/api/automation/import/run-now")
def dashboard_api_automation_import_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    providers = payload.providers or _env_settings_snapshot().get("auto_import_providers") or ["mercadolivre"]
    result = execute_import_run(providers, payload.limit)
    if scheduler is not None:
        scheduler._record_result("import", status="success" if not result.get("error") else "error", result=result)
    return result


@app.post("/dashboard/api/automation/social/run-now")
def dashboard_api_automation_social_run_now(payload: DashboardJobRunPayload, _: str = Depends(require_manager_auth)):
    settings = _env_settings_snapshot()
    platform, mode = _normalize_auto_social_action(
        payload.platform or settings.get("auto_social_platform") or "facebook",
        payload.mode or settings.get("auto_social_mode") or "reel_story",
    )
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
    if payload.auto_social_platform is not None or payload.auto_social_mode is not None:
        current_settings = _env_settings_snapshot()
        social_platform, social_mode = _normalize_auto_social_action(
            payload.auto_social_platform if payload.auto_social_platform is not None else current_settings.get("auto_social_platform"),
            payload.auto_social_mode if payload.auto_social_mode is not None else current_settings.get("auto_social_mode"),
        )
        updates["AUTO_SOCIAL_PLATFORM"] = social_platform
        updates["AUTO_SOCIAL_MODE"] = social_mode
    if payload.auto_social_limit is not None:
        updates["AUTO_SOCIAL_LIMIT"] = str(max(1, min(int(payload.auto_social_limit), 20)))
    if payload.auto_social_repeat_block_minutes is not None:
        updates["AUTO_SOCIAL_REPEAT_BLOCK_MINUTES"] = str(max(60, int(payload.auto_social_repeat_block_minutes)))
    if payload.whatsapp_api_base_url is not None:
        updates["WHATSAPP_API_BASE_URL"] = payload.whatsapp_api_base_url.strip()
    if payload.whatsapp_api_token is not None and payload.whatsapp_api_token.strip() != "":
        updates["WHATSAPP_API_TOKEN"] = payload.whatsapp_api_token.strip()
    if payload.whatsapp_group_target is not None:
        updates["WHATSAPP_GROUP_TARGET"] = payload.whatsapp_group_target.strip()
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
    if payload.youtube_client_id is not None:
        updates["YOUTUBE_CLIENT_ID"] = payload.youtube_client_id.strip()
    if payload.youtube_client_secret is not None and payload.youtube_client_secret.strip() != "":
        updates["YOUTUBE_CLIENT_SECRET"] = payload.youtube_client_secret.strip()
    if payload.youtube_redirect_uri is not None:
        updates["YOUTUBE_REDIRECT_URI"] = payload.youtube_redirect_uri.strip()
    if payload.ytdlp_cookies_from_browser is not None:
        updates["YTDLP_COOKIES_FROM_BROWSER"] = payload.ytdlp_cookies_from_browser.strip()
    if payload.ytdlp_cookies_file is not None:
        updates["YTDLP_COOKIES_FILE"] = payload.ytdlp_cookies_file.strip()
    if payload.gemini_api_key is not None and payload.gemini_api_key.strip() != "":
        updates["GEMINI_API_KEY"] = payload.gemini_api_key.strip()
    if payload.gemini_model is not None and payload.gemini_model.strip() != "":
        updates["GEMINI_MODEL"] = payload.gemini_model.strip()
    if payload.openai_api_key is not None and payload.openai_api_key.strip() != "":
        updates["OPENAI_API_KEY"] = payload.openai_api_key.strip()
    if payload.openai_shorts_rerank_model is not None and payload.openai_shorts_rerank_model.strip() != "":
        updates["OPENAI_SHORTS_RERANK_MODEL"] = payload.openai_shorts_rerank_model.strip()

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


@app.post("/dashboard/api/deploy/automation")
def dashboard_api_deploy_automation(_: str = Depends(require_manager_auth)):
    try:
        return execute_deploy_automation()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except paramiko.SSHException as e:
        raise HTTPException(status_code=502, detail=str(e))
    except OSError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/dashboard/api/whatsapp/groups")
def dashboard_api_whatsapp_groups(limit: int = 100, _: str = Depends(require_manager_auth)):
    try:
        return list_whatsapp_groups(limit=limit)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError as e:
        detail = e.response.text if e.response is not None else str(e)
        raise HTTPException(status_code=502, detail=detail)
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=str(e))


@app.get("/social/meta/post-previews")
def social_meta_post_previews(limit: int = 12, q: str = "", store: str = ""):
    db = SessionLocal()
    try:
        try:
            items = build_meta_post_previews(
                db,
                limit=limit,
                include_story_assets=False,
                search_query=q,
                store_filter=store,
            )
            blocked_recent_ids = _recent_social_offer_ids_within_minutes(db, _auto_social_repeat_block_minutes())
            items = [item for item in items if int(item.get("offer_id") or 0) not in blocked_recent_ids]
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
        result = publish_facebook_offer_batch(db, limit=payload.limit, offer_ids=payload.offer_ids)
        if int(result.get("count") or 0) > 0:
            result["asset_cleanup"] = _cleanup_generated_publish_assets()
        return result
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


@app.get("/integrations/youtube/oauth/callback")
def youtube_oauth_callback(code: str | None = None, state: str | None = None, error: str | None = None, error_description: str | None = None):
    if error:
        return HTMLResponse(f"<html><body><h2>OAuth YouTube falhou</h2><p>{error}</p><p>{error_description or ''}</p></body></html>")
    if not code:
        return HTMLResponse("<html><body><h2>OAuth YouTube incompleto</h2><p>Code nao recebido no callback.</p></body></html>", status_code=400)

    db = SessionLocal()
    try:
        profile = get_youtube_channel_profile_by_state(db, state or "")
        if not profile:
            return HTMLResponse("<html><body><h2>OAuth YouTube recusado</h2><p>State invalido no callback.</p></body></html>", status_code=400)
        tokens = exchange_youtube_code(
            code,
            client_id=str(profile.get("client_id") or ""),
            client_secret=str(profile.get("client_secret") or ""),
            redirect_uri=str(profile.get("redirect_uri") or ""),
        )
        updates = _youtube_profile_token_updates(tokens, profile)
        updates["oauth_state"] = ""
        access_token = str(updates.get("access_token") or profile.get("access_token") or "").strip()
        if access_token:
            channel = fetch_youtube_channel(access_token)
            thumbnails = channel.get("thumbnails") or {}
            updates["channel_id"] = channel.get("id") or None
            updates["channel_title"] = channel.get("title") or None
            updates["channel_custom_url"] = channel.get("custom_url") or None
            updates["channel_thumbnail_url"] = (
                (thumbnails.get("high") or {}).get("url")
                or (thumbnails.get("medium") or {}).get("url")
                or (thumbnails.get("default") or {}).get("url")
                or None
            )
        update_youtube_channel_profile(db, int(profile["id"]), updates)
        channel = _youtube_auth_snapshot(int(profile["id"]), refresh=False).get("channel") or {}
        channel_title = channel.get("title") or "canal conectado"
        return HTMLResponse(
            "<html><body>"
            "<h2>YouTube conectado</h2>"
            f"<p>Conta autorizada com sucesso para o perfil: {profile.get('name') or 'Canal'}</p>"
            f"<p>Canal autenticado: {channel_title}</p>"
            "<p>Voce pode fechar esta aba e voltar ao manager.</p>"
            "</body></html>"
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Falha no callback do YouTube: {e}")
    finally:
        db.close()


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
