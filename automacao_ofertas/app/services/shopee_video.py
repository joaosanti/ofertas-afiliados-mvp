from __future__ import annotations

import base64
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from base64 import urlsafe_b64encode
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

import httpx
import imageio_ffmpeg
from sqlalchemy import bindparam, text

from app.database import SessionLocal
from app.services.offer_card_asset import generate_offer_square_card_asset
from app.services.social_meta import download_source_video_asset, generate_reel_asset
from app.services.sftp_deploy import ensure_stories_dir, story_public_url


PROJECT_ROOT = Path(__file__).resolve().parents[3]
RUNTIME_ROOT = PROJECT_ROOT / "automacao_ofertas" / "runtime" / "shopee_video"
BUNDLED_MUSIC_DIR = PROJECT_ROOT / "automacao_ofertas" / "assets" / "music"
BUNDLED_DEFAULT_BG_MUSIC = BUNDLED_MUSIC_DIR / "mixkit-serene-view-443.mp3"
OFFER_VIDEO_UPLOAD_DIR = PROJECT_ROOT / "public_html" / "uploads" / "ofertas_videos"
TARGET_VIDEO_WIDTH = 1080
TARGET_VIDEO_HEIGHT = 1920
TARGET_VIDEO_FPS = 30

SELECT_DRAFT_SQL = text(
    """
    SELECT
      d.id AS draft_id,
      d.oferta_id,
      d.status AS draft_status,
      d.publish_mode,
      d.title_snapshot,
      d.caption AS draft_caption,
      d.affiliate_url AS draft_affiliate_url,
      d.offer_url AS draft_offer_url,
      d.video_source_url AS draft_video_source_url,
      d.image_url AS draft_image_url,
      o.id,
      o.slug,
      o.titulo,
      o.descricao,
      o.preco,
      o.preco_antigo,
      o.desconto_percentual,
      o.preco_pix,
      o.preco_outros_meios,
      o.parcelas_texto,
      o.frete_texto,
      o.avaliacao_nota,
      o.avaliacao_total,
      o.promocao_texto,
      o.loja,
      o.url_afiliado,
      o.cupom,
      o.imagem_url,
      o.imagem_urls_json,
      o.video_urls_json,
      o.categoria,
      o.tags,
      d.package_payload_json
    FROM shopee_video_drafts d
    INNER JOIN ofertas o
      ON o.id = d.oferta_id
    WHERE d.id = :draft_id
    LIMIT 1
    """
)

SELECT_OFFER_SQL = text(
    """
    SELECT
      NULL AS draft_id,
      o.id AS oferta_id,
      NULL AS draft_status,
      'manual' AS publish_mode,
      o.titulo AS title_snapshot,
      NULL AS draft_caption,
      o.url_afiliado AS draft_affiliate_url,
      CONCAT('/oferta/', o.slug) AS draft_offer_url,
      NULL AS draft_video_source_url,
      o.imagem_url AS draft_image_url,
      o.id,
      o.slug,
      o.titulo,
      o.descricao,
      o.preco,
      o.preco_antigo,
      o.desconto_percentual,
      o.preco_pix,
      o.preco_outros_meios,
      o.parcelas_texto,
      o.frete_texto,
      o.avaliacao_nota,
      o.avaliacao_total,
      o.promocao_texto,
      o.loja,
      o.url_afiliado,
      o.cupom,
      o.imagem_url,
      o.imagem_urls_json,
      o.video_urls_json,
      o.categoria,
      o.tags
    FROM ofertas o
    WHERE o.id = :offer_id
      AND LOWER(o.loja) = 'shopee'
      AND o.ativo = 1
    LIMIT 1
    """
)

SELECT_SOCIAL_OFFER_SQL = text(
    """
    SELECT
      NULL AS draft_id,
      o.id AS oferta_id,
      NULL AS draft_status,
      'manual' AS publish_mode,
      o.titulo AS title_snapshot,
      NULL AS draft_caption,
      o.url_afiliado AS draft_affiliate_url,
      CONCAT('/oferta/', o.slug) AS draft_offer_url,
      NULL AS draft_video_source_url,
      o.imagem_url AS draft_image_url,
      o.id,
      o.slug,
      o.titulo,
      o.descricao,
      o.preco,
      o.preco_antigo,
      o.desconto_percentual,
      o.preco_pix,
      o.preco_outros_meios,
      o.parcelas_texto,
      o.frete_texto,
      o.avaliacao_nota,
      o.avaliacao_total,
      o.promocao_texto,
      o.loja,
      o.url_afiliado,
      o.cupom,
      o.imagem_url,
      o.imagem_urls_json,
      o.video_urls_json,
      o.categoria,
      o.tags
    FROM ofertas o
    WHERE o.id = :offer_id
      AND o.ativo = 1
    LIMIT 1
    """
)

SELECT_DRAFT_OFFERS_SQL = text(
    """
    SELECT
      id,
      slug,
      titulo,
      preco,
      preco_antigo,
      desconto_percentual,
      preco_pix,
      parcelas_texto,
      frete_texto,
      categoria,
      cupom,
      imagem_url,
      url_afiliado,
      tags
    FROM ofertas
    WHERE id IN :ids
      AND ativo = 1
      AND LOWER(loja) = 'shopee'
    """
).bindparams(bindparam("ids", expanding=True))

SELECT_EXISTING_DRAFT_IDS_SQL = text(
    """
    SELECT oferta_id
    FROM shopee_video_drafts
    WHERE oferta_id IN :ids
    """
).bindparams(bindparam("ids", expanding=True))

UPSERT_DRAFT_SQL = text(
    """
    INSERT INTO shopee_video_drafts
      (oferta_id, status, publish_mode, title_snapshot, price_snapshot, caption, affiliate_url, offer_url, video_source_url, image_url, notes, creative_payload_json, package_status, api_status, created_by_admin_id, created_by_login, published_at, last_error, package_error)
    VALUES
      (:oferta_id, :status, :publish_mode, :title_snapshot, :price_snapshot, :caption, :affiliate_url, :offer_url, :video_source_url, :image_url, :notes, :creative_payload_json, :package_status, :api_status, :created_by_admin_id, :created_by_login, NULL, NULL, NULL)
    ON DUPLICATE KEY UPDATE
      status = VALUES(status),
      publish_mode = VALUES(publish_mode),
      title_snapshot = VALUES(title_snapshot),
      price_snapshot = VALUES(price_snapshot),
      caption = VALUES(caption),
      affiliate_url = VALUES(affiliate_url),
      offer_url = VALUES(offer_url),
      video_source_url = VALUES(video_source_url),
      image_url = VALUES(image_url),
      notes = VALUES(notes),
      creative_payload_json = VALUES(creative_payload_json),
      package_status = CASE
        WHEN package_payload_json IS NULL OR package_payload_json = '' THEN 'not_started'
        ELSE 'stale'
      END,
      api_status = VALUES(api_status),
      created_by_admin_id = VALUES(created_by_admin_id),
      created_by_login = VALUES(created_by_login),
      last_error = NULL,
      package_error = NULL,
      published_at = CASE WHEN VALUES(status) = 'published' THEN COALESCE(published_at, NOW()) ELSE published_at END
    """
)


def shopee_video_runtime_dir() -> Path:
    RUNTIME_ROOT.mkdir(parents=True, exist_ok=True)
    return RUNTIME_ROOT


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _slugify(value: Any) -> str:
    cleaned = re.sub(r"[^a-z0-9-]+", "-", str(value or "").strip().lower()).strip("-")
    return cleaned[:80] or "shopee-video"


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _decode_tag_url(tags: Any, prefix: str) -> str:
    for part in [item.strip() for item in str(tags or "").split(",") if item.strip()]:
        if not part.startswith(prefix):
            continue
        encoded = part[len(prefix):].strip()
        if not encoded:
            continue
        padding = "=" * (-len(encoded) % 4)
        try:
            decoded = base64.urlsafe_b64decode(encoded + padding).decode("utf-8")
        except Exception:  # noqa: BLE001
            continue
        normalized = _clean_text(decoded)
        if normalized.startswith(("http://", "https://")):
            return normalized
    return ""


def _site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/")


def _money(value: Any) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _discount_percent(offer: dict[str, Any]) -> int:
    explicit = offer.get("desconto_percentual")
    if explicit not in (None, ""):
        try:
            return max(0, int(float(explicit)))
        except (TypeError, ValueError):
            pass
    try:
        current = float(offer.get("preco") or 0)
        previous = float(offer.get("preco_antigo") or 0)
    except (TypeError, ValueError):
        return 0
    if current <= 0 or previous <= current:
        return 0
    return max(0, int(round(((previous - current) / previous) * 100)))


def _category_hashtags(category: str) -> list[str]:
    lowered = _clean_text(category).lower()
    mapping = [
        ("celular", ["#celular", "#smartphone"]),
        ("fone", ["#fonebluetooth", "#fone"]),
        ("beleza", ["#beleza", "#autocuidado"]),
        ("casa", ["#utilidadesdomesticas", "#achadinhosdecasa"]),
        ("cozinha", ["#cozinha", "#utilidadesdomesticas"]),
        ("moda", ["#moda", "#look"]),
        ("eletron", ["#eletronicos", "#gadget"]),
        ("gamer", ["#setupgamer", "#gamer"]),
    ]
    for keyword, hashtags in mapping:
        if keyword in lowered:
            return hashtags
    return ["#achadinhos", "#promocao"]


def _normalize_hashtag_token(value: Any) -> str:
    raw = _clean_text(value)
    if not raw or re.match(r"^https?://", raw, flags=re.IGNORECASE):
        return ""
    if ":" in raw:
        return ""
    slug = re.sub(r"[^a-z0-9]+", "", _slugify(raw))
    return f"#{slug}" if slug else ""


def _offer_hashtags(offer: dict[str, Any], limit: int = 6) -> list[str]:
    hashtags: list[str] = []
    raw_tags = re.split(r"[\r\n,]+", str(offer.get("tags") or ""))
    for raw_tag in raw_tags:
        normalized = _normalize_hashtag_token(raw_tag)
        if normalized and normalized not in hashtags:
            hashtags.append(normalized)
        if len(hashtags) >= max(1, limit):
            return hashtags

    for tag in _category_hashtags(_clean_text(offer.get("categoria") or "")):
        normalized = _normalize_hashtag_token(tag)
        if normalized and normalized not in hashtags:
            hashtags.append(normalized)
        if len(hashtags) >= max(1, limit):
            return hashtags

    for tag in _store_hashtags(offer):
        if tag not in hashtags:
            hashtags.append(tag)
        if len(hashtags) >= max(1, limit):
            break
    return hashtags


def _store_label(value: Any) -> str:
    lowered = _clean_text(value).lower()
    mapping = {
        "shopee": "Shopee",
        "amazon": "Amazon",
        "mercado livre": "Mercado Livre",
    }
    return mapping.get(lowered, _clean_text(value) or "Loja")


def _store_with_article(value: Any) -> str:
    lowered = _clean_text(value).lower()
    if lowered == "mercado livre":
        return "no Mercado Livre"
    if lowered == "amazon":
        return "na Amazon"
    if lowered == "shopee":
        return "na Shopee"
    label = _store_label(value)
    return f"na {label}"


def _store_of(value: Any) -> str:
    lowered = _clean_text(value).lower()
    if lowered == "mercado livre":
        return "do Mercado Livre"
    if lowered == "amazon":
        return "da Amazon"
    if lowered == "shopee":
        return "da Shopee"
    label = _store_label(value)
    return f"da {label}"


def _store_hashtags(offer: dict[str, Any]) -> list[str]:
    store = _clean_text(offer.get("loja") or offer.get("store")).lower()
    if store == "amazon":
        return ["#amazon", "#ofertas", "#achadinhos", "#promocao"]
    if store == "mercado livre":
        return ["#mercadolivre", "#ofertas", "#achadinhos", "#promocao"]
    return ["#shopee", "#shopeevideo", "#ofertas", "#achadinhos"]


def _truncate_text(value: Any, max_chars: int) -> str:
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text
    if max_chars <= 1:
        return text[:max_chars]
    return text[: max_chars - 1].rstrip() + "…"


def _compact_caption(offer: dict[str, Any], max_chars: int = 150) -> str:
    title = _clean_text(offer.get("titulo") or offer.get("title_snapshot") or "Oferta")
    price = _money(offer.get("preco"))
    discount = _discount_percent(offer)
    coupon = _clean_text(offer.get("cupom"))
    store = _store_label(offer.get("loja") or offer.get("store"))
    store_with_article = _store_with_article(store)
    hashtags = _offer_hashtags(offer, limit=5)
    hashtags_text = " ".join(hashtags)

    candidates: list[str] = []
    if coupon:
        candidates.append(f"Cupom {coupon} no {title} por {price}.")
        candidates.append(f"{title} com cupom por {price}.")
    if discount > 0:
        candidates.append(f"{title} com {discount}% off por {price}.")
    candidates.extend(
        [
            f"{title} por {price} {store_with_article}.",
            f"{title} por {price}.",
            f"Achado {store} por {price}.",
        ]
    )

    for candidate in candidates:
        final = _clean_text(f"{hashtags_text} {candidate}")
        if len(final) <= max_chars:
            return final

    reserve = len(hashtags_text) + 1 if hashtags_text else 0
    available = max(20, max_chars - reserve)
    short_title = _truncate_text(title, max(12, available - 12))
    fallback = _clean_text(f"{hashtags_text} {short_title} {price}")
    if len(fallback) <= max_chars:
        return fallback
    return _truncate_text(_clean_text(f"{hashtags_text} {price}"), max_chars)


def _brand_name() -> str:
    raw = _clean_text(os.getenv("SHOPEE_VIDEO_BRAND_NAME") or "Zero Preço")
    if not raw:
        return "Zero Preço"
    normalized = re.sub(r"(?i)\bzero\s+preco\b", "Zero Preço", raw)
    normalized = re.sub(r"(?i)\bzero\s+preço\b", "Zero Preço", normalized)
    return normalized or "Zero Preço"


def _normalized_category(category: Any) -> str:
    return _clean_text(category).lower()


def _category_matches(category: Any, keywords: tuple[str, ...]) -> bool:
    lowered = _normalized_category(category)
    return any(keyword in lowered for keyword in keywords)


def _offer_video_url(offer: dict[str, Any]) -> str:
    draft_video_url = _clean_text(offer.get("draft_video_source_url") or "")
    if draft_video_url.startswith(("http://", "https://")):
        return draft_video_url

    tags = offer.get("tags") or ""
    for prefix in ("offer_video_url:", "shopee_video_url:"):
        decoded_tag_url = _decode_tag_url(tags, prefix)
        if decoded_tag_url:
            return decoded_tag_url

    gallery = _decode_url_list(offer.get("video_urls") or offer.get("video_urls_json"))
    return gallery[0] if gallery else ""


def _offer_video_upload_dir() -> Path:
    OFFER_VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    return OFFER_VIDEO_UPLOAD_DIR


def _offer_video_public_url(filename: str) -> str:
    return f"{_site_base_url()}/uploads/ofertas_videos/{filename}"


def _upsert_tag_url(tags: str, prefix: str, url: str) -> str:
    normalized_url = _clean_text(url)
    if not normalized_url.startswith(("http://", "https://")):
        return str(tags or "")

    parts = [part.strip() for part in str(tags or "").split(",") if part.strip()]
    parts = [part for part in parts if not part.startswith(prefix)]
    encoded_url = urlsafe_b64encode(normalized_url.encode("utf-8")).decode("ascii").rstrip("=")
    parts.append(f"{prefix}{encoded_url}")
    return ",".join(dict.fromkeys(parts))


def _attach_generated_video_to_offer(offer: dict[str, Any], video_path: Path, *, label: str) -> dict[str, Any]:
    if not video_path.is_file():
        raise ValueError("Video gerado nao encontrado para anexar na oferta.")

    extension = video_path.suffix.lower()
    if extension not in {".mp4", ".webm", ".mov", ".m4v"}:
        extension = ".mp4"
    target_name = (
        f"oferta-video-auto-{int(offer['id'])}-"
        f"{_slugify(offer.get('slug') or offer.get('titulo') or 'oferta')}-"
        f"{secrets.token_hex(4)}{extension}"
    )
    target_path = _offer_video_upload_dir() / target_name
    shutil.copy2(video_path, target_path)
    public_url = _offer_video_public_url(target_name)

    db = SessionLocal()
    try:
        current = db.execute(
            text("SELECT tags FROM ofertas WHERE id = :offer_id LIMIT 1"),
            {"offer_id": int(offer["id"])},
        ).scalar_one_or_none()
        if current is None:
            raise ValueError("Oferta nao encontrada para anexar o video no admin.")
        updated_tags = _upsert_tag_url(str(current or ""), "offer_video_url:", public_url)
        db.execute(
            text("UPDATE ofertas SET tags = :tags WHERE id = :offer_id LIMIT 1"),
            {"offer_id": int(offer["id"]), "tags": updated_tags},
        )
        db.commit()
    except Exception:
        db.rollback()
        target_path.unlink(missing_ok=True)
        raise
    finally:
        db.close()

    return {
        "path": str(target_path),
        "filename": target_name,
        "content_type": "video/mp4",
        "public_url": public_url,
        "label": label,
        "offer_id": int(offer["id"]),
        "tag_prefix": "offer_video_url:",
        "persistent": True,
    }


def _best_ready_video_file(files: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]] | None:
    for key in ("reel_video_final", "reel_video_tts_subtitled", "reel_video_tts", "reel_video", "source_video"):
        entry = files.get(key)
        if not isinstance(entry, dict):
            continue
        path = Path(str(entry.get("path") or "").strip())
        if path.is_file():
            return key, entry
    return None


def _decode_url_list(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        raw_items = decoded if isinstance(decoded, list) else [raw]

    urls: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        url = _clean_text(item)
        if not url.startswith(("http://", "https://")):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _offer_image_gallery_urls(offer: dict[str, Any]) -> list[str]:
    gallery = _decode_url_list(offer.get("imagem_urls") or offer.get("imagem_urls_json"))
    primary = _clean_text(offer.get("imagem_url") or offer.get("draft_image_url"))
    if primary and primary not in gallery:
        gallery.insert(0, primary)
    return gallery


def _offer_video_gallery_urls(offer: dict[str, Any]) -> list[str]:
    gallery = _decode_url_list(offer.get("video_urls") or offer.get("video_urls_json"))
    primary = _offer_video_url(offer)
    if primary and primary not in gallery:
        gallery.insert(0, primary)
    return gallery


def _tts_enabled() -> bool:
    value = (os.getenv("SHOPEE_VIDEO_TTS_ENABLED") or "true").strip().lower()
    return value not in {"0", "false", "off", "no", "nao"}


def _package_simple_mode() -> bool:
    value = (os.getenv("SHOPEE_VIDEO_SIMPLE_MODE") or "true").strip().lower()
    return value not in {"0", "false", "off", "no", "nao"}


def _package_target_duration_seconds() -> float:
    raw = (os.getenv("SHOPEE_VIDEO_TARGET_DURATION_SECONDS") or "10").strip() or "10"
    try:
        parsed = float(raw)
    except ValueError:
        return 10.0
    return max(4.0, min(parsed, 60.0))


def _openai_api_key_optional() -> str:
    return (os.getenv("OPENAI_API_KEY") or "").strip()


def _tts_model() -> str:
    return (os.getenv("SHOPEE_VIDEO_TTS_MODEL") or "gpt-4o-mini-tts").strip()


def _tts_max_attempts() -> int:
    raw = (os.getenv("SHOPEE_VIDEO_TTS_MAX_ATTEMPTS") or "3").strip() or "3"
    try:
        parsed = int(raw)
    except ValueError:
        return 3
    return max(1, min(parsed, 5))


def _tts_voice() -> str:
    return (os.getenv("SHOPEE_VIDEO_TTS_VOICE") or "coral").strip()


def _tts_voice_for_offer(offer: dict[str, Any]) -> str:
    category = offer.get("categoria") or ""
    if _category_matches(category, ("moda", "beleza", "maqui", "decor", "casa", "cozinha", "infantil", "pet")):
        return (os.getenv("SHOPEE_VIDEO_TTS_VOICE_FEMALE") or os.getenv("SHOPEE_VIDEO_TTS_VOICE_DEFAULT") or "coral").strip()
    if _category_matches(category, ("eletron", "gamer", "ferrament", "automot", "esport", "fitness")):
        return (os.getenv("SHOPEE_VIDEO_TTS_VOICE_MALE") or os.getenv("SHOPEE_VIDEO_TTS_VOICE_DEFAULT") or "sage").strip()
    return (os.getenv("SHOPEE_VIDEO_TTS_VOICE_DEFAULT") or _tts_voice()).strip()


def _tts_instructions() -> str:
    return (
        os.getenv("SHOPEE_VIDEO_TTS_INSTRUCTIONS")
        or (
            "Fale em português do Brasil, com tom confiante e natural, ritmo dinâmico "
            "e locução de oferta premium, sem soar robótico. Pronuncie corretamente "
            "'preço', 'vídeo' e a marca 'Zero Preço'."
        )
    ).strip()


def _tts_instructions_for_offer(offer: dict[str, Any]) -> str:
    base = _tts_instructions()
    category = offer.get("categoria") or ""
    if _category_matches(category, ("moda", "beleza", "decor", "casa")):
        return f"{base} Valorize sensacao de desejo, acabamento premium e estilo de vitrine."
    if _category_matches(category, ("eletron", "gamer", "ferrament", "automot")):
        return f"{base} Destaque performance, praticidade e percepcao de tecnologia."
    if _category_matches(category, ("fitness", "esport", "saude")):
        return f"{base} Traga energia, urgencia e foco em beneficio rapido."
    return base


def _tts_instructions() -> str:
    configured = (os.getenv("SHOPEE_VIDEO_TTS_INSTRUCTIONS") or "").strip()
    if configured:
        return configured
    return (
        "Fale em portugues do Brasil com energia de locutor de oferta, sorriso na voz, "
        "mais empolgacao comercial e urgencia leve. Soe humano, quente e convincente, "
        "nunca monotono ou robotico. Dê mais intencao nas palavras de preco, desconto, "
        "cupom e chamada para acao. Pronuncie corretamente 'preco', 'video' e a marca "
        "'Zero Preco'."
    )


def _tts_instructions_for_offer(offer: dict[str, Any]) -> str:
    base = _tts_instructions()
    category = offer.get("categoria") or ""
    if _category_matches(category, ("moda", "beleza", "decor", "casa")):
        return f"{base} Valorize desejo, estilo, conforto e sensacao de oportunidade bonita de vitrine."
    if _category_matches(category, ("eletron", "gamer", "ferrament", "automot")):
        return f"{base} Destaque performance, praticidade, tecnologia e impacto de oferta boa."
    if _category_matches(category, ("fitness", "esport", "saude")):
        return f"{base} Traga energia alta, urgencia e sensacao de resultado rapido."
    return base


def _ffmpeg_command() -> list[str]:
    system = _system_ffmpeg_command()
    if system:
        return system
    try:
        return [imageio_ffmpeg.get_ffmpeg_exe()]
    except Exception as exc:  # noqa: BLE001
        raise ValueError("Nao consegui localizar o ffmpeg para finalizar o video narrado.") from exc


def _system_ffmpeg_command() -> list[str] | None:
    binary = shutil.which("ffmpeg")
    return [binary] if binary else None


def _ffmpeg_command_candidates() -> list[list[str]]:
    commands: list[list[str]] = []
    system = _system_ffmpeg_command()
    if system:
        commands.append(system)
    try:
        bundled = [imageio_ffmpeg.get_ffmpeg_exe()]
    except Exception:  # noqa: BLE001
        bundled = None
    if bundled and bundled not in commands:
        commands.append(bundled)
    if not commands:
        raise ValueError("Nao consegui localizar o ffmpeg para finalizar o video narrado.")
    return commands


def _ffmpeg_h264_video_args() -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-threads",
        "1",
        "-preset",
        "veryfast",
        "-crf",
        "23",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]


def _ffmpeg_mpeg4_video_args() -> list[str]:
    return [
        "-c:v",
        "mpeg4",
        "-q:v",
        "5",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]


def _ffprobe_command() -> list[str] | None:
    system_probe = shutil.which("ffprobe")
    if system_probe:
        return [system_probe]

    ffmpeg_binary = Path(_ffmpeg_command()[0])
    probe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
    probe_binary = ffmpeg_binary.with_name(probe_name)
    return [str(probe_binary)] if probe_binary.is_file() else None


def _escape_subtitles_filter_path(path: Path) -> str:
    raw = str(path.resolve()).replace("\\", "/")
    if re.match(r"^[A-Za-z]:", raw):
        raw = raw[0] + "\\:" + raw[2:]
    return raw.replace("'", "\\'")


def _probe_media_duration_seconds(media_path: Path) -> float:
    command = _ffprobe_command()
    if not media_path.is_file():
        return 0.0
    if command:
        completed = subprocess.run(
            command + [
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode == 0:
            try:
                return max(0.0, float((completed.stdout or "0").strip()))
            except ValueError:
                pass

    completed = subprocess.run(
        _ffmpeg_command()
        + [
            "-hide_banner",
            "-i",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    stderr = (completed.stderr or "") + "\n" + (completed.stdout or "")
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2})\.(\d{1,2})", stderr)
    if not match:
        return 0.0
    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    centiseconds = int(match.group(4))
    return max(0.0, (hours * 3600) + (minutes * 60) + seconds + (centiseconds / 100.0))


def _probe_video_dimensions(media_path: Path) -> tuple[int, int]:
    command = _ffprobe_command()
    if not media_path.is_file() or not command:
        return (0, 0)

    completed = subprocess.run(
        command
        + [
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(media_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return (0, 0)

    raw = (completed.stdout or "").strip().lower()
    if "x" not in raw:
        return (0, 0)

    width_raw, height_raw = raw.split("x", 1)
    try:
        return (max(0, int(width_raw)), max(0, int(height_raw)))
    except ValueError:
        return (0, 0)


def _normalize_video_for_shopee(
    video_path: Path,
    output_path: Path,
    *,
    max_duration_seconds: float | None = None,
) -> dict[str, Any]:
    if not video_path.is_file():
        raise ValueError("Video base nao encontrado para normalizar em 1080x1920.")

    width, height = _probe_video_dimensions(video_path)
    filter_chain = (
        f"scale={TARGET_VIDEO_WIDTH}:{TARGET_VIDEO_HEIGHT}:force_original_aspect_ratio=decrease:flags=lanczos,"
        f"pad={TARGET_VIDEO_WIDTH}:{TARGET_VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color=0x0a2a67,"
        "setsar=1"
    )
    errors: list[str] = []

    for ffmpeg in _ffmpeg_command_candidates():
        output_path.unlink(missing_ok=True)
        command = ffmpeg + [
            "-y",
            "-i",
            str(video_path),
            "-vf",
            filter_chain,
            "-r",
            str(TARGET_VIDEO_FPS),
            "-c:v",
            "libx264",
            "-threads",
            "1",
            "-preset",
            "veryfast",
            "-profile:v",
            "main",
            "-level:v",
            "4.1",
            "-crf",
            "24",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
        ]
        if max_duration_seconds and max_duration_seconds > 0:
            command.extend(["-t", f"{float(max_duration_seconds):.2f}"])
        command.append(str(output_path))
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode == 0 and output_path.is_file():
            return {
                "path": str(output_path),
                "filename": output_path.name,
                "content_type": "video/mp4",
                "width": TARGET_VIDEO_WIDTH,
                "height": TARGET_VIDEO_HEIGHT,
                "fps": TARGET_VIDEO_FPS,
                "generated_from": "source_video",
                "source_dimensions": {"width": width, "height": height},
            }

        detail = ((completed.stderr or "") + "\n" + (completed.stdout or "")).strip()
        errors.append(f"{' '.join(ffmpeg)}: {detail[:220]}")

    raise ValueError(f"Falha ao normalizar o video para 1080x1920. {' | '.join(errors[:3])}")


def _split_voiceover_chunks(script_text: str, *, max_words: int = 6) -> list[str]:
    sentences = [segment.strip() for segment in re.split(r"(?<=[\.\!\?\:])\s+", _clean_text(script_text)) if segment.strip()]
    chunks: list[str] = []
    for sentence in sentences:
        words = sentence.split()
        if len(words) <= max_words:
            chunks.append(sentence)
            continue
        current: list[str] = []
        for word in words:
            current.append(word)
            if len(current) >= max_words:
                chunks.append(" ".join(current).strip())
                current = []
        if current:
            chunks.append(" ".join(current).strip())
    return chunks or ([_clean_text(script_text)] if _clean_text(script_text) else [])


def _format_srt_timestamp(value: float) -> str:
    total_ms = max(0, int(round(float(value) * 1000)))
    hours, remainder = divmod(total_ms, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, milliseconds = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def _write_voiceover_srt(script_text: str, duration_seconds: float, output_path: Path) -> dict[str, Any]:
    chunks = _split_voiceover_chunks(script_text)
    if not chunks:
        raise ValueError("Roteiro de narracao vazio para gerar legenda.")
    duration = max(2.0, float(duration_seconds or 0.0))
    slot = duration / max(1, len(chunks))
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        start = (index - 1) * slot
        end = duration if index == len(chunks) else min(duration, index * slot)
        lines.extend(
            [
                str(index),
                f"{_format_srt_timestamp(start)} --> {_format_srt_timestamp(end)}",
                chunk,
                "",
            ]
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    return {
        "path": str(output_path),
        "filename": output_path.name,
        "content_type": "application/x-subrip",
    }


def _background_music_source() -> str:
    configured = (os.getenv("SHOPEE_VIDEO_BG_MUSIC_PATH") or os.getenv("SHOPEE_VIDEO_BG_MUSIC_URL") or "").strip()
    if configured:
        return configured
    return str(BUNDLED_DEFAULT_BG_MUSIC) if BUNDLED_DEFAULT_BG_MUSIC.is_file() else ""


def _reel_duration_seconds(creative: dict[str, Any], *, narration_duration: float = 0.0) -> float:
    creative_duration = max(1.5, float(creative.get("duration_seconds") or 0.0))
    if narration_duration <= 0:
        return min(creative_duration, _package_target_duration_seconds())
    return max(creative_duration, round(float(narration_duration) + 0.5, 2))


def _background_music_source_for_offer(offer: dict[str, Any]) -> str:
    category = offer.get("categoria") or ""
    if _category_matches(category, ("moda", "beleza")):
        return (
            os.getenv("SHOPEE_VIDEO_BG_MUSIC_MODA_PATH")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_MODA_URL")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_BELEZA_PATH")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_BELEZA_URL")
            or _background_music_source()
        ).strip()
    if _category_matches(category, ("casa", "cozinha", "decor", "lar")):
        return (
            os.getenv("SHOPEE_VIDEO_BG_MUSIC_CASA_PATH")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_CASA_URL")
            or _background_music_source()
        ).strip()
    if _category_matches(category, ("eletron", "gamer", "ferrament", "automot")):
        return (
            os.getenv("SHOPEE_VIDEO_BG_MUSIC_TECH_PATH")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_TECH_URL")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_GAMER_PATH")
            or os.getenv("SHOPEE_VIDEO_BG_MUSIC_GAMER_URL")
            or _background_music_source()
        ).strip()
    return _background_music_source()


def _creative_angle(offer: dict[str, Any], discount: int, coupon: str) -> str:
    if coupon:
        return "cupom e ação imediata"
    if discount >= 35:
        return "desconto agressivo"
    if offer.get("preco_pix") not in (None, "", 0, 0.0):
        return "preço no Pix"
    if _clean_text(offer.get("frete_texto")):
        return "benefício de frete"
    return "achadinho útil do dia"


def _creative_seed(offer: dict[str, Any], salt: str = "") -> int:
    base = "|".join(
        [
            str(offer.get("id") or offer.get("oferta_id") or ""),
            _clean_text(offer.get("titulo") or offer.get("title_snapshot") or ""),
            str(salt or ""),
        ]
    )
    digest = sha256(base.encode("utf-8", errors="ignore")).hexdigest()
    return int(digest[:8], 16)


def _pick_variant(offer: dict[str, Any], salt: str, options: list[str]) -> str:
    if not options:
        return ""
    return options[_creative_seed(offer, salt) % len(options)]


def _draft_ready_status(offer: dict[str, Any], mode: str) -> tuple[str, str, str]:
    normalized_mode = "api" if mode == "api" else "manual"
    if normalized_mode == "api":
        return (
            "api_blocked",
            "not_supported",
            "Sem endpoint publico confirmado para publicar no Shopee Video. Use este rascunho no fluxo manual.",
        )

    has_video = bool(_offer_video_url(offer))
    has_image = bool(_clean_text(offer.get("imagem_url")))
    if has_video or has_image:
        return (
            "manual_ready",
            "manual_only",
            "Rascunho pronto para gerar pacote pro e postar manualmente no app da Shopee.",
        )
    return (
        "needs_video",
        "manual_only",
        "Oferta sem video e sem imagem suficiente para gerar pacote agora.",
    )


def _build_creative_payload_legacy(offer: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(offer.get("titulo") or offer.get("title_snapshot") or "Oferta")
    price = _money(offer.get("preco"))
    old_price = _money(offer.get("preco_antigo")) if offer.get("preco_antigo") not in (None, "", 0, 0.0) else ""
    pix_price = _money(offer.get("preco_pix")) if offer.get("preco_pix") not in (None, "", 0, 0.0) else ""
    discount = _discount_percent(offer)
    coupon = _clean_text(offer.get("cupom"))
    shipping = _clean_text(offer.get("frete_texto"))
    installments = _clean_text(offer.get("parcelas_texto"))
    category = _clean_text(offer.get("categoria") or "Achadinhos")
    store = _store_label(offer.get("loja") or offer.get("store"))
    store_with_article = _store_with_article(store)
    store_of = _store_of(store)
    angle = _creative_angle(offer, discount, coupon)
    brand_name = _brand_name()

    if coupon:
        hook = f"Achado com cupom na Shopee: {title}"
        cover = f"CUPOM + {price}"
    elif discount >= 35:
        hook = f"Olha esse achado na Shopee com {discount}% off"
        cover = f"{discount}% OFF"
    elif pix_price:
        hook = "Esse produto ficou com preço forte no Pix"
        cover = f"NO PIX {pix_price}"
    else:
        hook = "Achadinho da Shopee que vale a pena abrir agora"
        cover = f"ACHADO {price}"

    cta = f"Abre o link e vê os detalhes completos com {brand_name}."
    if coupon:
        cta = f"Clique no link e teste o cupom {coupon}."
    cta_final = f"Abre o link e vê os detalhes completos com {brand_name}."

    value_points = [title]
    if old_price:
        value_points.append(f"Antes {old_price}, agora {price}.")
    else:
        value_points.append(f"Preço atual em destaque: {price}.")
    if pix_price:
        value_points.append(f"No Pix pode ficar por {pix_price}.")
    if installments:
        value_points.append(installments)
    if shipping:
        value_points.append(shipping)
    if coupon:
        value_points.append(f"Cupom visivel: {coupon}.")

    price_proof = price
    if discount > 0:
        price_proof = f"{price} | {discount}% OFF"

    detail_line = ""
    if pix_price:
        detail_line = f"No Pix: {pix_price}"
    elif installments:
        detail_line = installments
    elif shipping:
        detail_line = shipping
    elif coupon:
        detail_line = f"Cupom {coupon}"
    else:
        detail_line = "Confira o valor atualizado no link."

    hashtags = [
        "#shopee",
        "#shopeevideo",
        "#ofertas",
        "#achadinhos",
        *_category_hashtags(category),
    ]
    hashtags = list(dict.fromkeys([tag for tag in hashtags if tag]))

    caption_lines = [
        hook,
        f"Produto: {title}",
        f"Preço destaque: {price}",
    ]
    if old_price:
        caption_lines.append(f"Preço anterior: {old_price}")
    if pix_price:
        caption_lines.append(f"Preço no Pix: {pix_price}")
    if installments:
        caption_lines.append(f"Parcelamento: {installments}")
    if shipping:
        caption_lines.append(f"Frete: {shipping}")
    if coupon:
        caption_lines.append(f"Cupom: {coupon}")
    caption_lines.extend(
        [
            "Confira os detalhes no link do vídeo.",
            cta,
            " ".join(hashtags),
        ]
    )

    shot_plan = [
        {
            "segment": "0-2s",
            "goal": "gancho inicial",
            "overlay": hook,
            "direction": "Abrir com texto grande e close do produto.",
        },
        {
            "segment": "2-5s",
            "goal": "prova de oferta",
            "overlay": f"{price}" + (f" | {discount}% OFF" if discount > 0 else ""),
            "direction": "Mostrar preço, benefício principal e movimento rápido.",
        },
        {
            "segment": "5-8s",
            "goal": "fechamento com CTA",
            "overlay": cta_final,
            "direction": "Encerrar com marca, chamada para abrir o link e repetir o produto.",
        },
    ]

    edit_notes = [
        "Usar vídeo vertical 9:16.",
        "Gancho forte no primeiro segundo com texto em caixa alta.",
        "Cortes curtos e ritmo rápido, sem pausas longas.",
        "Mostrar preço e benefício principal antes dos 4 segundos.",
        "Deixar a CTA visivel no fechamento.",
    ]
    if coupon:
        edit_notes.append(f"Reforcar o cupom {coupon} no frame final.")
    if discount >= 35:
        edit_notes.append("Destacar o desconto com selo grande.")

    publish_checklist = [
        "Confirmar se o produto exibido e o produto marcado são o mesmo item.",
        "Revisar preço e cupom antes de publicar.",
        "Checar se o link de afiliado está correto.",
        "Manter título curto e direto no app da Shopee.",
        "Publicar na vertical com capa legível.",
    ]

    scene_overlays = [
        {
            "scene_id": "hook",
            "eyebrow": f"ACHADO {store.upper()}",
            "headline": hook,
            "subline": _clean_text(title[:88]),
            "sticker": cover,
        },
        {
            "scene_id": "proof",
            "eyebrow": "PROVA DE OFERTA",
            "headline": price_proof,
            "subline": detail_line,
            "sticker": f"CUPOM {coupon}" if coupon else (f"{discount}% OFF" if discount > 0 else "OFERTA DO DIA"),
        },
        {
            "scene_id": "cta",
            "eyebrow": "FECHAMENTO",
            "headline": cta_final,
            "subline": "Abra o link e confira os detalhes completos.",
            "sticker": "LINK DO PRODUTO",
            "brand": brand_name,
            "button_label": "ABRIR AGORA",
        },
    ]

    voiceover_lines = [
        hook,
        f"Produto em destaque: {title}.",
        f"Preço atual: {price}.",
    ]
    if old_price:
        voiceover_lines.append(f"Antes estava em {old_price}.")
    if pix_price:
        voiceover_lines.append(f"No Pix pode sair por {pix_price}.")
    elif installments:
        voiceover_lines.append(installments)
    if shipping:
        voiceover_lines.append(shipping)
    if coupon:
        voiceover_lines.append(f"Teste o cupom {coupon}.")
    voiceover_lines.append(cta)

    return {
        "angle": angle,
        "brand_name": brand_name,
        "hook": hook,
        "cover_text": cover,
        "cta_text": cta,
        "cta_final_text": cta_final,
        "duration_seconds": 8,
        "value_points": value_points,
        "hashtags": hashtags,
        "caption": "\n".join([line for line in caption_lines if line]).strip(),
        "shot_plan": shot_plan,
        "scene_overlays": scene_overlays,
        "voiceover_script": " ".join([line for line in voiceover_lines if line]).strip(),
        "edit_notes": edit_notes,
        "publish_checklist": publish_checklist,
    }


def _build_creative_payload(offer: dict[str, Any]) -> dict[str, Any]:
    title = _clean_text(offer.get("titulo") or offer.get("title_snapshot") or "Oferta")
    price = _money(offer.get("preco"))
    old_price_value = float(offer.get("preco_antigo") or 0) if offer.get("preco_antigo") not in (None, "") else 0.0
    old_price = _money(old_price_value) if old_price_value > 0 else ""
    pix_price_value = float(offer.get("preco_pix") or 0) if offer.get("preco_pix") not in (None, "") else 0.0
    pix_price = _money(pix_price_value) if pix_price_value > 0 else ""
    discount = _discount_percent(offer)
    coupon = _clean_text(offer.get("cupom"))
    shipping = _clean_text(offer.get("frete_texto"))
    installments = _clean_text(offer.get("parcelas_texto"))
    category = _clean_text(offer.get("categoria") or "Achadinhos")
    store = _store_label(offer.get("loja") or offer.get("store"))
    store_with_article = _store_with_article(store)
    store_of = _store_of(store)
    angle = _creative_angle(offer, discount, coupon)
    brand_name = _brand_name()

    if coupon:
        hook = _pick_variant(
            offer,
            "hook_coupon",
            [
                f"Cupom {store_with_article} e produto chamando clique: {title}",
                f"Achado com cupom {store_with_article}: {title}",
                f"Se liga nesse achado com cupom: {title}",
            ],
        )
        cover = _pick_variant(offer, "cover_coupon", [f"CUPOM + {price}", f"CUPOM {coupon}", f"OFERTA + {price}"])
    elif discount >= 35:
        hook = _pick_variant(
            offer,
            "hook_discount",
            [
                f"Olha esse achado {store_with_article} com {discount}% off",
                f"Desconto forte {store_with_article}: {discount}% off nesse produto",
                f"Esse achado apareceu com {discount}% de desconto",
            ],
        )
        cover = _pick_variant(offer, "cover_discount", [f"{discount}% OFF", f"CAIU PRA {price}", f"ACHADO {discount}%"])
    elif pix_price:
        hook = _pick_variant(
            offer,
            "hook_pix",
            [
                f"Esse produto ficou forte no Pix: {title}",
                "Preco no Pix que chamou atencao agora",
                f"Olha como esse item ficou no Pix: {pix_price}",
            ],
        )
        cover = _pick_variant(offer, "cover_pix", [f"NO PIX {pix_price}", f"PIX {pix_price}", f"PIX + OFERTA"])
    else:
        hook = _pick_variant(
            offer,
            "hook_general",
            [
                f"Passando esse achado {store_of} que chamou atencao",
                f"Se liga nesse achadinho {store_of} que apareceu agora",
                f"Olha esse produto {store_of} com cara de venda rapida",
                f"Achei esse item {store_with_article} e o pre\u00e7o ficou interessante",
            ],
        )
        cover = _pick_variant(offer, "cover_general", [f"ACHADO {price}", f"OFERTA {price}", "VALE O CLIQUE"])

    cta = _pick_variant(
        offer,
        "cta_primary",
        [
            f"Abre o link e v\u00ea os detalhes completos com {brand_name}.",
        ],
    )
    if coupon:
        cta = _pick_variant(
            offer,
            "cta_coupon",
            [
                f"Clica no link e testa o cupom {coupon}.",
                f"Abre o link agora e valida o cupom {coupon}.",
                f"Toca no link e aproveita o cupom {coupon} enquanto aparece.",
            ],
        )
    cta_final = _pick_variant(
        offer,
        "cta_final",
        [
            f"Abre o link e v\u00ea os detalhes completos com {brand_name}.",
        ],
    )

    value_points = [title]
    if old_price and old_price_value > float(offer.get("preco") or 0):
        value_points.append(f"Antes {old_price}, agora {price}.")
    else:
        value_points.append(f"Preco atual em destaque: {price}.")
    if pix_price:
        value_points.append(f"No Pix pode ficar por {pix_price}.")
    if installments:
        value_points.append(installments)
    if shipping:
        value_points.append(shipping)
    if coupon:
        value_points.append(f"Cupom em destaque: {coupon}.")

    price_proof = price if discount <= 0 else f"{price} | {discount}% OFF"
    detail_line = "Confira o valor atualizado no link."
    if pix_price:
        detail_line = f"No Pix: {pix_price}"
    elif installments:
        detail_line = installments
    elif shipping:
        detail_line = shipping
    elif coupon:
        detail_line = f"Cupom {coupon}"

    hashtags = _offer_hashtags(offer, limit=6)

    caption_lines = [hook, f"Produto: {title}", f"Preco destaque: {price}"]
    if old_price and old_price_value > float(offer.get("preco") or 0):
        caption_lines.append(f"Preco anterior: {old_price}")
    if pix_price:
        caption_lines.append(f"Preco no Pix: {pix_price}")
    if installments:
        caption_lines.append(f"Parcelamento: {installments}")
    if shipping:
        caption_lines.append(f"Frete: {shipping}")
    if coupon:
        caption_lines.append(f"Cupom: {coupon}")
    caption_lines.extend([cta, " ".join([tag for tag in hashtags if tag])])

    shot_plan = [
        {"segment": "0-2s", "goal": "gancho inicial", "overlay": hook, "direction": "Abrir com close forte, texto grande e ritmo de oferta."},
        {"segment": "2-5s", "goal": "prova de oferta", "overlay": price_proof, "direction": "Mostrar preco, produto e vantagem principal sem enrolar."},
        {"segment": "5-8s", "goal": "fechamento com CTA", "overlay": cta_final, "direction": "Fechar com energia, CTA clara e marca no frame final."},
    ]

    scene_overlays = [
        {"scene_id": "hook", "eyebrow": f"ACHADO {store.upper()}", "headline": hook, "subline": _clean_text(title[:88]), "sticker": cover},
        {"scene_id": "proof", "eyebrow": "PROVA DE OFERTA", "headline": price_proof, "subline": detail_line, "sticker": f"CUPOM {coupon}" if coupon else (f"{discount}% OFF" if discount > 0 else "OFERTA DO DIA")},
        {"scene_id": "cta", "eyebrow": "FECHAMENTO", "headline": cta_final, "subline": "Abra o link e confira os detalhes completos.", "sticker": "LINK DO PRODUTO", "brand": brand_name, "button_label": "ABRIR AGORA"},
    ]

    edit_notes = [
        "Usar video vertical 9:16.",
        "Gancho forte no primeiro segundo com texto em caixa alta.",
        "Cortes curtos, mais energia e ritmo de venda.",
        "Mostrar preco e beneficio principal antes dos 4 segundos.",
        "Fechar com CTA visivel e marca no final.",
    ]
    if coupon:
        edit_notes.append(f"Reforcar o cupom {coupon} no fechamento.")
    if discount >= 35:
        edit_notes.append("Destacar o desconto com selo grande e urgente.")

    publish_checklist = [
        "Confirmar se o produto exibido e o produto marcado sao o mesmo item.",
        "Revisar preco e cupom antes de publicar.",
        "Checar se o link de afiliado esta correto.",
        f"Manter titulo curto e direto no app da {store}.",
        "Publicar na vertical com capa legivel.",
    ]

    voiceover_lines = [
        _pick_variant(
            offer,
            "voice_open",
            [
                f"Se liga nesse achadinho {store_of} que apareceu agora.",
                f"Olha essa oferta {store_of} que chamou atencao por aqui.",
                f"Presta atencao nesse achado {store_of} que vale abrir agora.",
                f"Acabei de encontrar essa oferta {store_of} e o pre\u00e7o chamou aten\u00e7\u00e3o.",
            ],
        ),
        f"Produto: {title}.",
        f"Pre\u00e7o destaque: {price}.",
    ]
    if old_price and old_price_value > float(offer.get("preco") or 0):
        voiceover_lines.append(f"Antes estava em {old_price}.")
    if pix_price:
        voiceover_lines.append(f"No Pix pode sair por {pix_price}.")
    elif installments:
        voiceover_lines.append(installments)
    if shipping:
        voiceover_lines.append(shipping)
    if coupon:
        voiceover_lines.append(f"Testa o cupom {coupon}.")
    voiceover_lines.append(
        _pick_variant(
            offer,
            "voice_bridge",
            [
                "Vale conferir esse pre\u00e7o com calma no link.",
                "Esse valor ficou interessante para esse produto.",
                "Oferta boa assim vale abrir o link e olhar os detalhes.",
            ],
        )
    )
    voiceover_lines.append(cta)

    return {
        "angle": angle,
        "brand_name": brand_name,
        "hook": hook,
        "cover_text": cover,
        "cta_text": cta,
        "cta_final_text": cta_final,
        "duration_seconds": 8,
        "value_points": value_points,
        "hashtags": hashtags,
        "caption": "\n".join([line for line in caption_lines if line]).strip(),
        "short_caption": _compact_caption(offer, 150),
        "shot_plan": shot_plan,
        "scene_overlays": scene_overlays,
        "voiceover_script": _generate_voiceover_script_with_gemini(offer) or " ".join([line for line in voiceover_lines if line]).strip(),
        "edit_notes": edit_notes,
        "publish_checklist": publish_checklist,
    }


def _write_text_file(path: Path, content: str) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((content or "").strip() + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "filename": path.name,
        "content_type": "text/plain",
    }


def _write_json_file(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "path": str(path),
        "filename": path.name,
        "content_type": "application/json",
    }


def _build_brief_text(offer: dict[str, Any], creative: dict[str, Any]) -> str:
    lines = [
        "PACOTE PROFISSIONAL SHOPEE VIDEO",
        "",
        f"Produto: {_clean_text(offer.get('titulo'))}",
        f"Categoria: {_clean_text(offer.get('categoria'))}",
        f"Ângulo: {_clean_text(creative.get('angle'))}",
        f"Hook: {_clean_text(creative.get('hook'))}",
        f"Capa: {_clean_text(creative.get('cover_text'))}",
        f"CTA: {_clean_text(creative.get('cta_text'))}",
        "",
        "Pontos de venda:",
    ]
    for point in creative.get("value_points") or []:
        lines.append(f"- {_clean_text(point)}")
    lines.extend(["", "Plano de cortes:"])
    for item in creative.get("shot_plan") or []:
        lines.append(
            f"- {item.get('segment')}: {item.get('goal')} | {item.get('overlay')} | {item.get('direction')}"
        )
    lines.extend(["", "Edicao recomendada:"])
    for note in creative.get("edit_notes") or []:
        lines.append(f"- {note}")
    return "\n".join(lines).strip()


def _build_checklist_text(creative: dict[str, Any]) -> str:
    lines = ["CHECKLIST DE PUBLICAÇÃO", ""]
    for item in creative.get("publish_checklist") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).strip()


def _build_voiceover_text(creative: dict[str, Any]) -> str:
    return "\n".join(
        [
            "ROTEIRO DE NARRAÇÃO",
            "",
            _clean_text(creative.get("voiceover_script")),
        ]
    ).strip()


def _generate_voiceover_script_with_gemini(offer: dict[str, Any]) -> str:
    gemini_key = (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY") or "").strip()
    if not gemini_key:
        return ""

    title = _clean_text(offer.get("titulo") or offer.get("title_snapshot") or "Oferta")
    price = _money(offer.get("preco"))
    old_price_value = float(offer.get("preco_antigo") or 0) if offer.get("preco_antigo") not in (None, "") else 0.0
    old_price = _money(old_price_value) if old_price_value > 0 else ""
    coupon = _clean_text(offer.get("cupom"))
    store = _store_label(offer.get("loja") or offer.get("store"))
    category = _clean_text(offer.get("categoria") or "Achadinhos")

    prompt = (
        "Escreva um roteiro curto e falado para um video promocional estilo 'Achadinho' nas redes sociais (Instagram Reels / TikTok / Shopee Video) em portugues do Brasil. "
        "O tom deve ser empolgante, direto e natural de quem esta indicando uma compra imperdivel. "
        "Tamanho ideal: 18 a 30 palavras (para dar entre 6 a 9 segundos de fala). "
        f"Produto: {title}\n"
        f"Loja: {store}\n"
        f"Preco: {price}" + (f" (estava {old_price})" if old_price else "") + "\n" +
        (f"Cupom: {coupon}\n" if coupon else "") +
        f"Categoria: {category}\n\n"
        "Estrutura do roteiro:\n"
        "- Comece com um gancho atrativo como: 'Olha esse achadinho que acabei de encontrar!' ou 'Se liga nesse achado imperdivel!' ou 'Gente, olha o preco desse produto!'\n"
        "- Fale o produto e o preco promocional de forma fluida.\n"
        "- Finalize chamando para clicar no link da bio ou nos comentarios.\n"
        "Retorne APENAS o texto puro do roteiro a ser narrado, sem aspas, titulos ou explicacoes."
    )

    model = os.getenv("GEMINI_MODEL") or "gemini-2.0-flash"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={gemini_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 150},
    }
    try:
        with httpx.Client(timeout=15) as client:
            resp = client.post(url, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates") or []
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts") or []
                    if parts and "text" in parts[0]:
                        script = parts[0]["text"].strip().strip('"').replace("\n", " ")
                        if len(script) >= 15:
                            return script
    except Exception:
        pass
    return ""


def _generate_edge_tts_audio(script_text: str, output_path: Path, *, voice: str) -> dict[str, Any]:
    import asyncio
    import edge_tts

    voice_map = {
        "coral": "pt-BR-FranciscaNeural",
        "nova": "pt-BR-FranciscaNeural",
        "shimmer": "pt-BR-ThalitaNeural",
        "sage": "pt-BR-AntonioNeural",
        "alloy": "pt-BR-AntonioNeural",
        "echo": "pt-BR-FabioNeural",
        "onyx": "pt-BR-FabioNeural",
        "female": "pt-BR-FranciscaNeural",
        "male": "pt-BR-AntonioNeural",
    }
    target_voice = voice_map.get(voice.lower(), voice if "pt-br" in voice.lower() else "pt-BR-FranciscaNeural")

    async def _run():
        communicate = edge_tts.Communicate(_clean_text(script_text), target_voice)
        await communicate.save(str(output_path))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    asyncio.run(_run())

    if not output_path.is_file() or output_path.stat().st_size == 0:
        raise ValueError("Falha ao gerar audio via sintetizador neural edge-tts.")

    return {
        "path": str(output_path),
        "filename": output_path.name,
        "content_type": "audio/mpeg",
        "provider": "edge_tts",
        "voice": target_voice,
    }


def _generate_openai_tts_audio(script_text: str, output_path: Path, *, voice: str, instructions: str) -> dict[str, Any]:
    api_key = _openai_api_key_optional()
    if not api_key:
        raise ValueError("OPENAI_API_KEY nao configurada para gerar a narracao automatica.")

    payload = {
        "model": _tts_model(),
        "voice": voice,
        "input": _clean_text(script_text),
        "instructions": instructions,
        "response_format": "mp3",
    }
    last_error: Exception | None = None
    audio_bytes = b""
    for attempt in range(1, _tts_max_attempts() + 1):
        try:
            with httpx.Client(timeout=180, follow_redirects=True) as client:
                response = client.post(
                    "https://api.openai.com/v1/audio/speech",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                audio_bytes = response.content
            if audio_bytes:
                break
            raise ValueError("A OpenAI retornou audio vazio para a narracao.")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt >= _tts_max_attempts():
                raise ValueError(f"Falha ao gerar a narracao apos {attempt} tentativa(s): {str(exc)}") from exc
            time.sleep(min(2.5, 0.8 * attempt))

    if not audio_bytes:
        if last_error is not None:
            raise ValueError(str(last_error)) from last_error
        raise ValueError("A OpenAI retornou audio vazio para a narracao.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(audio_bytes)
    return {
        "path": str(output_path),
        "filename": output_path.name,
        "content_type": "audio/mpeg",
        "provider": "openai",
    }


def _generate_tts_audio(script_text: str, output_path: Path, *, voice: str, instructions: str) -> dict[str, Any]:
    # 1. Tentar edge-tts primeiro (gratuito, sem limites, vozes neurais brasileiras ultra-realistas)
    try:
        return _generate_edge_tts_audio(script_text, output_path, voice=voice)
    except Exception as edge_err:
        # 2. Fallback para OpenAI se disponivel
        api_key = _openai_api_key_optional()
        if api_key:
            try:
                return _generate_openai_tts_audio(script_text, output_path, voice=voice, instructions=instructions)
            except Exception:
                pass
        raise edge_err


def _mux_video_with_audio(video_path: Path, audio_path: Path, output_path: Path) -> dict[str, Any]:
    if not video_path.is_file():
        raise ValueError("Video base nao encontrado para juntar com a narracao.")
    if not audio_path.is_file():
        raise ValueError("Audio da narracao nao encontrado para finalizar o video.")

    video_duration = _probe_media_duration_seconds(video_path)
    audio_duration = _probe_media_duration_seconds(audio_path)
    loop_video = audio_duration > 0 and video_duration > 0 and audio_duration > video_duration + 0.05
    attempts = [
        ("copy", ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]),
        ("libx264", [*_ffmpeg_h264_video_args(), "-c:a", "aac", "-b:a", "192k"]),
        ("mpeg4", [*_ffmpeg_mpeg4_video_args(), "-c:a", "aac", "-b:a", "192k"]),
    ]
    errors: list[str] = []
    for ffmpeg in _ffmpeg_command_candidates():
        for label, video_args in attempts:
            output_path.unlink(missing_ok=True)
            command = ffmpeg + [
                "-y",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
            ]
            if loop_video:
                command.extend(["-stream_loop", "-1"])
            command.extend([
                "-i",
                str(video_path),
                "-i",
                str(audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                *video_args,
            ])
            if loop_video and audio_duration > 0:
                command.extend(["-t", f"{audio_duration:.3f}"])
            elif video_duration > 0:
                command.extend(["-af", "apad", "-t", f"{video_duration:.3f}"])
            else:
                command.append("-shortest")
            command.append(str(output_path))
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode == 0 and output_path.is_file():
                return {
                    "path": str(output_path),
                    "filename": output_path.name,
                    "content_type": "video/mp4",
                }
            detail = (completed.stderr or completed.stdout or "").strip()
            errors.append(f"{' '.join(ffmpeg)} [{label}]: {detail[:220]}")

    raise ValueError(f"Falha ao gerar o video narrado via ffmpeg. {' | '.join(errors[:4])}")


def _prepare_background_music(job_dir: Path, offer: dict[str, Any]) -> dict[str, Any] | None:
    source = _background_music_source_for_offer(offer)
    if not source:
        return None

    if source.startswith(("http://", "https://")):
        extension = Path(source.split("?", 1)[0]).suffix.lower()
        if extension not in {".mp3", ".wav", ".m4a", ".aac", ".ogg"}:
            extension = ".mp3"
        destination = job_dir / f"background-music{extension}"
        with httpx.Client(timeout=120, follow_redirects=True) as client:
            response = client.get(source)
            response.raise_for_status()
            payload = response.content
        if not payload:
            raise ValueError("Download da trilha retornou arquivo vazio.")
        destination.write_bytes(payload)
    else:
        source_path = Path(source)
        if not source_path.is_file():
            raise ValueError("Arquivo configurado em SHOPEE_VIDEO_BG_MUSIC_PATH nao foi encontrado.")
        destination = job_dir / source_path.name
        if destination.resolve() != source_path.resolve():
            destination.write_bytes(source_path.read_bytes())
        else:
            destination = source_path

    return {
        "path": str(destination),
        "filename": destination.name,
        "content_type": "audio/mpeg",
    }


def _burn_subtitles_into_video(video_path: Path, subtitle_path: Path, output_path: Path) -> dict[str, Any]:
    if not video_path.is_file():
        raise ValueError("Video narrado nao encontrado para queimar legenda.")
    if not subtitle_path.is_file():
        raise ValueError("Arquivo de legenda nao encontrado para queimar no video.")

    subtitle_filter = _escape_subtitles_filter_path(subtitle_path)
    attempts = [
        ("libx264", _ffmpeg_h264_video_args()),
        ("mpeg4", _ffmpeg_mpeg4_video_args()),
    ]
    errors: list[str] = []
    for ffmpeg in _ffmpeg_command_candidates():
        for label, video_args in attempts:
            output_path.unlink(missing_ok=True)
            command = ffmpeg + [
                "-y",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vf",
                f"subtitles='{subtitle_filter}'",
                *video_args,
                "-c:a",
                "copy",
                str(output_path),
            ]
            completed = subprocess.run(command, capture_output=True, text=True, check=False)
            if completed.returncode == 0 and output_path.is_file():
                return {
                    "path": str(output_path),
                    "filename": output_path.name,
                    "content_type": "video/mp4",
                }
            detail = (completed.stderr or completed.stdout or "").strip()
            errors.append(f"{' '.join(ffmpeg)} [{label}]: {detail[:220]}")

    raise ValueError(f"Falha ao queimar a legenda no video. {' | '.join(errors[:4])}")


def _mix_background_music_with_ducking(video_path: Path, music_path: Path, output_path: Path) -> dict[str, Any]:
    if not video_path.is_file():
        raise ValueError("Video legendado nao encontrado para mixar com trilha.")
    if not music_path.is_file():
        raise ValueError("Trilha de fundo nao encontrada para mixar.")

    filter_complex = (
        "[1:a]volume=0.16[music];"
        "[music][0:a]sidechaincompress=threshold=0.03:ratio=10:attack=18:release=320:makeup=1[ducked];"
        "[0:a][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
    )
    errors: list[str] = []
    for ffmpeg in _ffmpeg_command_candidates():
        output_path.unlink(missing_ok=True)
        command = ffmpeg + [
            "-y",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(video_path),
            "-stream_loop",
            "-1",
            "-i",
            str(music_path),
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            str(output_path),
        ]
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode == 0 and output_path.is_file():
            return {
                "path": str(output_path),
                "filename": output_path.name,
                "content_type": "video/mp4",
            }
        detail = (completed.stderr or completed.stdout or "").strip()
        errors.append(f"{' '.join(ffmpeg)}: {detail[:220]}")

    raise ValueError(f"Falha ao mixar a trilha com ducking automatico. {' | '.join(errors[:3])}")


def _copy_video_as_final(video_path: Path, output_path: Path) -> dict[str, Any]:
    if not video_path.is_file():
        raise ValueError("Video base nao encontrado para gerar o video final.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.unlink(missing_ok=True)
    shutil.copy2(video_path, output_path)
    return {
        "path": str(output_path),
        "filename": output_path.name,
        "content_type": "video/mp4",
    }


def _fetch_offer_payload(*, draft_id: int | None = None, offer_id: int | None = None) -> dict[str, Any]:
    db = SessionLocal()
    try:
        if draft_id is not None:
            row = db.execute(SELECT_DRAFT_SQL, {"draft_id": int(draft_id)}).mappings().first()
        elif offer_id is not None:
            row = db.execute(SELECT_OFFER_SQL, {"offer_id": int(offer_id)}).mappings().first()
            if row is None:
                row = db.execute(SELECT_SOCIAL_OFFER_SQL, {"offer_id": int(offer_id)}).mappings().first()
        else:
            row = None
        if row is None:
            raise ValueError("Oferta nao encontrada para gerar o pacote.")
        payload = dict(row)
        package_payload_raw = payload.get("package_payload_json")
        if package_payload_raw:
            try:
                payload["package_payload"] = json.loads(str(package_payload_raw))
            except json.JSONDecodeError:
                payload["package_payload"] = {}
        else:
            payload["package_payload"] = {}
        return payload
    finally:
        db.close()


def _fetch_social_offer_payload(*, offer_id: int) -> dict[str, Any]:
    db = SessionLocal()
    try:
        row = db.execute(SELECT_SOCIAL_OFFER_SQL, {"offer_id": int(offer_id)}).mappings().first()
        if row is None:
            raise ValueError("Oferta nao encontrada para gerar o video social.")
        return dict(row)
    finally:
        db.close()


def queue_shopee_video_drafts_for_offers(
    db,
    offer_ids: list[int],
    *,
    mode: str = "manual",
    actor_user_id: int | None = None,
    actor_login: str | None = None,
) -> dict[str, Any]:
    normalized_ids = sorted({int(item) for item in offer_ids if int(item) > 0})
    if not normalized_ids:
        return {"count": 0, "created": 0, "updated": 0, "items": []}

    existing_ids = {
        int(value)
        for value in db.execute(SELECT_EXISTING_DRAFT_IDS_SQL, {"ids": normalized_ids}).scalars().all()
    }
    rows = db.execute(SELECT_DRAFT_OFFERS_SQL, {"ids": normalized_ids}).mappings().all()

    created = 0
    updated = 0
    items: list[dict[str, Any]] = []
    normalized_mode = "api" if mode == "api" else "manual"

    for row in rows:
        offer = dict(row)
        status, api_status, notes = _draft_ready_status(offer, normalized_mode)
        creative_payload = _build_creative_payload(offer)
        video_url = _offer_video_url(offer) or None
        db.execute(
            UPSERT_DRAFT_SQL,
            {
                "oferta_id": int(offer["id"]),
                "status": status,
                "publish_mode": normalized_mode,
                "title_snapshot": str(offer.get("titulo") or ""),
                "price_snapshot": float(offer.get("preco") or 0),
                "caption": str(creative_payload.get("caption") or ""),
                "affiliate_url": str(offer.get("url_afiliado") or ""),
                "offer_url": f"/oferta/{str(offer.get('slug') or '')}",
                "video_source_url": video_url,
                "image_url": str(offer.get("imagem_url") or ""),
                "notes": notes,
                "creative_payload_json": json.dumps(creative_payload, ensure_ascii=False),
                "package_status": "not_started",
                "api_status": api_status,
                "created_by_admin_id": actor_user_id,
                "created_by_login": actor_login,
            },
        )
        action = "updated" if int(offer["id"]) in existing_ids else "created"
        if action == "created":
            created += 1
        else:
            updated += 1
        items.append(
            {
                "offer_id": int(offer["id"]),
                "title": str(offer.get("titulo") or ""),
                "status": status,
                "has_video": bool(video_url),
                "action": action,
            }
        )

    return {"count": len(items), "created": created, "updated": updated, "items": items}


def build_shopee_video_package(*, draft_id: int | None = None, offer_id: int | None = None) -> dict[str, Any]:
    payload = _fetch_offer_payload(draft_id=draft_id, offer_id=offer_id)
    creative = _build_creative_payload(payload)
    simple_mode = _package_simple_mode()

    created_at = _utc_now()
    job_id = f"shopee-video-{int(payload['id'])}-{created_at.strftime('%Y%m%d%H%M%S')}"
    job_dir = shopee_video_runtime_dir() / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, dict[str, Any]] = {}
    warnings: list[str] = []

    caption_file = _write_text_file(job_dir / "caption.txt", str(creative.get("caption") or ""))
    short_caption_file = _write_text_file(job_dir / "caption-short.txt", str(creative.get("short_caption") or ""))
    brief_file = _write_text_file(job_dir / "brief.txt", _build_brief_text(payload, creative))
    checklist_file = _write_text_file(job_dir / "publish-checklist.txt", _build_checklist_text(creative))
    voiceover_file = _write_text_file(job_dir / "voiceover.txt", _build_voiceover_text(creative))
    files["caption"] = caption_file
    files["caption_short"] = short_caption_file
    files["brief"] = brief_file
    files["checklist"] = checklist_file
    files["voiceover"] = voiceover_file

    metadata_payload: dict[str, Any] = {
        "job_id": job_id,
        "created_at_utc": created_at.isoformat(),
        "draft_id": int(payload["draft_id"]) if payload.get("draft_id") is not None else None,
        "offer_id": int(payload["id"]),
        "slug": str(payload.get("slug") or ""),
        "title": str(payload.get("titulo") or ""),
        "price": float(payload.get("preco") or 0),
        "old_price": float(payload.get("preco_antigo")) if payload.get("preco_antigo") not in (None, "") else None,
        "affiliate_url": str(payload.get("url_afiliado") or payload.get("draft_affiliate_url") or ""),
        "offer_url": str(payload.get("draft_offer_url") or ""),
        "image_url": str(payload.get("imagem_url") or payload.get("draft_image_url") or ""),
        "source_video_url": _offer_video_url(payload),
        "reel_source": "image_gallery",
        "image_gallery_urls": _offer_image_gallery_urls(payload),
        "video_gallery_urls": _offer_video_gallery_urls(payload),
        "tts": {
            "enabled": _tts_enabled(),
            "provider": "openai",
            "model": _tts_model(),
            "voice": _tts_voice_for_offer(payload),
            "generated": False,
            "subtitle_generated": False,
        },
        "simple_mode": simple_mode,
        "creative": creative,
        "warnings": warnings,
    }
    metadata_file = _write_json_file(job_dir / "metadata.json", metadata_payload)
    files["metadata"] = metadata_file

    try:
        square_card = generate_offer_square_card_asset(payload, suffix="shopee-video")
        files["square_card"] = {
            "path": str(square_card["file_path"]),
            "filename": str(square_card["filename"]),
            "content_type": "image/jpeg",
            "public_url": str(square_card.get("public_url") or ""),
        }
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Square card indisponivel: {str(exc)}")

    voiceover_script = _clean_text(creative.get("voiceover_script"))
    narration_duration = 0.0
    if _tts_enabled():
        if voiceover_script:
            try:
                audio_path = job_dir / "voiceover.mp3"
                selected_voice = _tts_voice_for_offer(payload)
                selected_instructions = _tts_instructions_for_offer(payload)
                metadata_payload["tts"]["voice"] = selected_voice
                tts_audio = _generate_tts_audio(
                    voiceover_script,
                    audio_path,
                    voice=selected_voice,
                    instructions=selected_instructions,
                )
                if not simple_mode:
                    files["tts_audio"] = tts_audio
                metadata_payload["tts"]["provider"] = tts_audio.get("provider", "edge_tts")
                metadata_payload["tts"]["generated"] = True
                narration_duration = _probe_media_duration_seconds(Path(tts_audio["path"]))
                metadata_payload["tts"]["duration_seconds"] = round(narration_duration, 2)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Narracao automatica indisponivel: {str(exc)}")
        else:
            warnings.append("Narracao automatica pulada porque o roteiro ficou vazio.")

    reel_duration = _reel_duration_seconds(creative, narration_duration=narration_duration)
    metadata_payload["creative"]["duration_seconds"] = reel_duration

    source_video_url = _offer_video_url(payload)
    if source_video_url and not simple_mode:
        try:
            source_video = download_source_video_asset(payload, source_video_url)
            source_video_entry = {
                "path": str(source_video["file_path"]),
                "filename": str(source_video["filename"]),
                "content_type": "video/mp4",
                "public_url": str(source_video.get("public_url") or ""),
                "source_url": source_video_url,
            }
            files["source_video"] = source_video_entry
            try:
                normalized_source_path = job_dir / f"source-video-{int(payload['id'])}-1080x1920.mp4"
                normalized_source_video = _normalize_video_for_shopee(
                    Path(source_video["file_path"]),
                    normalized_source_path,
                    max_duration_seconds=reel_duration,
                )
                files["reel_video"] = {
                    **normalized_source_video,
                    "source_url": source_video_url,
                }
                metadata_payload["reel_source"] = "source_video_normalized"
                metadata_payload["source_video_dimensions"] = normalized_source_video.get("source_dimensions")
                metadata_payload["reel_video_dimensions"] = {
                    "width": TARGET_VIDEO_WIDTH,
                    "height": TARGET_VIDEO_HEIGHT,
                }
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Video original baixado, mas sem normalizacao HD: {str(exc)}")
                files["reel_video"] = {
                    **source_video_entry,
                    "generated_from": "source_video",
                }
                metadata_payload["reel_source"] = "source_video"
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Video original nao baixado para usar como reel base: {str(exc)}")

    if "reel_video" not in files:
        try:
            reel_asset = generate_reel_asset(payload, duration_seconds=reel_duration, creative=creative)
            files["reel_video"] = {
                "path": str(reel_asset["file_path"]),
                "filename": str(reel_asset["filename"]),
                "content_type": "video/mp4",
                "public_url": str(reel_asset.get("public_url") or ""),
                "generated_from": "image_gallery",
            }
            poster_url = str(reel_asset.get("poster_url") or "")
            if poster_url:
                files["poster"] = {
                    "path": str((Path(reel_asset["file_path"]).parent / Path(poster_url).name)),
                    "filename": Path(poster_url).name,
                    "content_type": "image/jpeg",
                    "public_url": poster_url,
                }
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Video base gerado por imagem indisponivel: {str(exc)}")

    if "tts_audio" in files and "reel_video" in files:
        try:
            narrated_path = job_dir / (Path(files["reel_video"]["filename"]).stem + "-narrado.mp4")
            narrated_video = _mux_video_with_audio(Path(files["reel_video"]["path"]), Path(files["tts_audio"]["path"]), narrated_path)
            files["reel_video_tts"] = narrated_video
            audio_duration = narration_duration or _probe_media_duration_seconds(Path(files["tts_audio"]["path"]))
            subtitle_path = job_dir / "voiceover.srt"
            subtitle_entry = _write_voiceover_srt(voiceover_script, audio_duration, subtitle_path)
            files["subtitle_srt"] = subtitle_entry
            metadata_payload["tts"]["subtitle_generated"] = True
            subtitled_path = job_dir / (Path(files["reel_video"]["filename"]).stem + "-legendado.mp4")
            subtitled_video = _burn_subtitles_into_video(Path(narrated_video["path"]), Path(subtitle_entry["path"]), subtitled_path)
            files["reel_video_tts_subtitled"] = subtitled_video
            try:
                music_entry = _prepare_background_music(job_dir, payload)
            except Exception as exc:  # noqa: BLE001
                music_entry = None
                warnings.append(f"Trilha de fundo indisponivel: {str(exc)}")
            if music_entry:
                files["music_bed"] = music_entry
                final_path = job_dir / (Path(files["reel_video"]["filename"]).stem + "-final.mp4")
                final_video = _mix_background_music_with_ducking(Path(subtitled_video["path"]), Path(music_entry["path"]), final_path)
                files["reel_video_final"] = final_video
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Narracao automatica indisponivel: {str(exc)}")

    if "tts_audio" not in files and metadata_payload["tts"]["generated"] and "reel_video" in files:
        try:
            audio_path = job_dir / "voiceover.mp3"
            narrated_path = job_dir / (Path(files["reel_video"]["filename"]).stem + "-narrado.mp4")
            narrated_video = _mux_video_with_audio(Path(files["reel_video"]["path"]), audio_path, narrated_path)
            final_source = narrated_video
            try:
                music_entry = _prepare_background_music(job_dir, payload)
            except Exception as exc:  # noqa: BLE001
                music_entry = None
                warnings.append(f"Trilha de fundo indisponivel: {str(exc)}")
            final_path = job_dir / (Path(files["reel_video"]["filename"]).stem + "-final.mp4")
            if music_entry:
                files["music_bed"] = music_entry
                final_video = _mix_background_music_with_ducking(Path(final_source["path"]), Path(music_entry["path"]), final_path)
            else:
                final_video = _copy_video_as_final(Path(final_source["path"]), final_path)
            files["reel_video_final"] = {
                **final_video,
                "generated_from": "reel_video_tts",
            }
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Narracao automatica indisponivel: {str(exc)}")

    if "reel_video_final" not in files and "reel_video" in files:
        try:
            final_path = job_dir / (Path(files["reel_video"]["filename"]).stem + "-final.mp4")
            final_video = _copy_video_as_final(Path(files["reel_video"]["path"]), final_path)
            files["reel_video_final"] = {
                **final_video,
                "generated_from": "reel_video",
            }
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Video final simplificado indisponivel: {str(exc)}")

    if source_video_url and "source_video" not in files:
        try:
            source_video = download_source_video_asset(payload, source_video_url)
            files["source_video"] = {
                "path": str(source_video["file_path"]),
                "filename": str(source_video["filename"]),
                "content_type": "video/mp4",
                "public_url": str(source_video.get("public_url") or ""),
                "source_url": source_video_url,
            }
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"Video original nao baixado: {str(exc)}")

    metadata_payload["warnings"] = warnings
    metadata_payload["files"] = files
    metadata_file = _write_json_file(job_dir / "metadata.json", metadata_payload)
    files["metadata"] = metadata_file

    return {
        "ok": True,
        "job_id": job_id,
        "offer_id": int(payload["id"]),
        "draft_id": int(payload["draft_id"]) if payload.get("draft_id") is not None else None,
        "created_at_utc": created_at.isoformat(),
        "creative": creative,
        "files": files,
        "warnings": warnings,
    }


def build_shopee_social_video_asset(*, offer_id: int) -> dict[str, Any]:
    payload = _fetch_social_offer_payload(offer_id=offer_id)
    package = build_shopee_video_package(offer_id=offer_id)
    files = package.get("files") if isinstance(package.get("files"), dict) else {}
    creative = package.get("creative") if isinstance(package.get("creative"), dict) else {}
    store = _store_label(payload.get("loja") or "Social")
    best_ready_video = _best_ready_video_file(files)
    if best_ready_video is None:
        raise ValueError("Nao consegui gerar um video pronto para publicar no social.")

    source_key, source_entry = best_ready_video
    source_path = Path(str(source_entry.get("path") or "").strip())
    if not source_path.is_file():
        raise ValueError("O video escolhido para o social nao foi encontrado no disco.")

    extension = source_path.suffix.lower()
    if extension not in {".mp4", ".mov", ".m4v", ".webm"}:
        extension = ".mp4"
    target_filename = f"offer-{int(offer_id)}-{_slugify(store)}-social-{source_key}{extension}"
    target_path = ensure_stories_dir() / target_filename
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)

    return {
        "ok": True,
        "offer_id": int(offer_id),
        "filename": target_filename,
        "file_path": str(target_path),
        "public_url": story_public_url(target_filename),
        "store": store,
        "source_key": source_key,
        "voiceover_script": _clean_text(creative.get("voiceover_script")),
        "warnings": list(package.get("warnings") or []),
        "package_job_id": str(package.get("job_id") or ""),
    }


def attach_generated_package_video(*, draft_id: int) -> dict[str, Any]:
    payload = _fetch_offer_payload(draft_id=draft_id)
    package_payload = payload.get("package_payload") if isinstance(payload.get("package_payload"), dict) else {}
    files = package_payload.get("files") if isinstance(package_payload.get("files"), dict) else {}
    best_ready_video = _best_ready_video_file(files)
    if best_ready_video is None:
        raise ValueError("Este pacote ainda nao tem video pronto para aplicar na oferta.")

    attach_key, attach_entry = best_ready_video
    attached_video = _attach_generated_video_to_offer(payload, Path(str(attach_entry["path"])), label=attach_key)
    return {
        "ok": True,
        "draft_id": int(draft_id),
        "offer_id": int(payload["id"]),
        "video_source_key": attach_key,
        "offer_video_url": attached_video["public_url"],
        "attached": attached_video,
    }
