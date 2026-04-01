import html
import json
import math
import os
import re
import shutil
import time
from base64 import urlsafe_b64decode
from hashlib import sha1
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx
import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import bindparam, text

from app.services.dashboard_data import ensure_dashboard_tables
from app.services.offer_card_asset import clean_offer_highlight_text, generate_offer_square_card_asset, normalize_installments_text
from app.services.sftp_deploy import deploy_stories_via_sftp, ensure_stories_dir, story_public_url


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
META_REFRESH_WINDOW_SECONDS = 7 * 24 * 60 * 60


def _prefer_system_ffmpeg_for_imageio() -> None:
    binary = shutil.which("ffmpeg")
    if binary and os.environ.get("IMAGEIO_FFMPEG_EXE") != binary:
        os.environ["IMAGEIO_FFMPEG_EXE"] = binary


def _story_video_codec_candidates() -> list[str]:
    return ["libx264", "mpeg4"]


def _story_video_output_params(*, codec: str) -> list[str]:
    params = [
        "-threads",
        "1",
        "-movflags",
        "+faststart",
    ]
    if codec == "libx264":
        params.extend(
            [
                "-preset",
                "veryfast",
                "-crf",
                "24",
            ]
        )
    elif codec == "mpeg4":
        params.extend(
            [
                "-q:v",
                "5",
            ]
        )
    return params


def _close_imageio_writer_safely(writer: Any) -> str | None:
    try:
        writer.close()
    except Exception as exc:  # noqa: BLE001
        return str(exc)
    return None


SELECT_TOP_OFFERS_SQL = text(
    """
    SELECT
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
      o.destaque,
      o.criado_em,
      o.atualizado_em,
      COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c
      ON c.oferta_id = o.id
      AND c.criado_em >= NOW() - INTERVAL 30 DAY
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.imagem_url IS NOT NULL
      AND o.imagem_url <> ''
      AND (
        :store_filter = ''
        OR LOWER(o.loja) = LOWER(:store_filter)
      )
      AND (
        :search_query = ''
        OR o.titulo LIKE :search_like
        OR o.slug LIKE :search_like
        OR o.loja LIKE :search_like
        OR o.categoria LIKE :search_like
      )
    GROUP BY o.id, o.slug, o.titulo, o.descricao, o.preco, o.preco_antigo, o.desconto_percentual, o.preco_pix, o.preco_outros_meios, o.parcelas_texto, o.frete_texto, o.avaliacao_nota, o.avaliacao_total, o.promocao_texto, o.loja, o.url_afiliado, o.cupom, o.imagem_url, o.imagem_urls_json, o.video_urls_json, o.categoria, o.tags, o.destaque, o.criado_em, o.atualizado_em
    ORDER BY o.criado_em DESC, o.id DESC
    LIMIT :limit
    OFFSET :offset
    """
)

SELECT_OFFERS_BY_IDS_SQL = text(
    """
    SELECT
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
      o.destaque,
      o.criado_em,
      o.atualizado_em,
      COUNT(c.id) AS clicks
    FROM ofertas o
    LEFT JOIN cliques c
      ON c.oferta_id = o.id
      AND c.criado_em >= NOW() - INTERVAL 30 DAY
    WHERE o.ativo = 1
      AND (o.expira_em IS NULL OR o.expira_em > NOW())
      AND o.imagem_url IS NOT NULL
      AND o.imagem_url <> ''
      AND o.id IN :offer_ids
    GROUP BY o.id, o.slug, o.titulo, o.descricao, o.preco, o.preco_antigo, o.desconto_percentual, o.preco_pix, o.preco_outros_meios, o.parcelas_texto, o.frete_texto, o.avaliacao_nota, o.avaliacao_total, o.promocao_texto, o.loja, o.url_afiliado, o.cupom, o.imagem_url, o.imagem_urls_json, o.video_urls_json, o.categoria, o.tags, o.destaque, o.criado_em, o.atualizado_em
    ORDER BY o.criado_em DESC, o.id DESC
    """
).bindparams(bindparam("offer_ids", expanding=True))

CATEGORY_LABELS = {
    "mlb1055": "Celulares e Smartphones",
    "mlb1714": "Mouses",
    "mlb135384": "Smartwatches",
    "mlb7457": "Fones e Kits Viva Voz",
    "mlb264715": "Escovas Eletricas",
    "mlb120425": "Umidificadores",
    "mlb456045": "Fritadeiras Eletricas",
    "mlb48666": "Panelas Eletricas",
    "mlb120373": "Panela de Arroz",
    "mlb196208": "Fones de Ouvido",
    "mlb3843": "Caixas Bluetooth",
    "mlb268503": "Difusores de Aromas Eletricos",
    "mlb11507": "Caixas Acusticas",
    "mlb271858": "Smartbands",
    "mlb439402": "Panelas a Vapor",
    "mlb433422": "Escovas Alisadoras para Barba",
    "mlb264184": "Cadeiras de Banho",
    "mlb31682": "Panelas de Oleo",
    "mlb107501": "Cacarolas e Caldeiroes",
    "mlb1664": "Fones",
    "mlb418472": "Teclados",
}


def _decode_tag_url(tags: str | None, prefix: str) -> str | None:
    for raw_tag in str(tags or "").split(","):
        tag = raw_tag.strip()
        if not tag.startswith(prefix):
            continue
        encoded = tag[len(prefix):].strip()
        if not encoded:
            continue
        padded = encoded + "=" * (-len(encoded) % 4)
        try:
            value = urlsafe_b64decode(padded.encode("ascii")).decode("utf-8").strip()
        except Exception:  # noqa: BLE001
            continue
        if value.startswith(("http://", "https://")):
            return value
    return None


def _offer_source_video_url(offer: dict[str, Any]) -> str | None:
    manual_video_url = _decode_tag_url(offer.get("tags"), "offer_video_url:")
    if manual_video_url:
        return manual_video_url
    return _decode_tag_url(offer.get("tags"), "shopee_video_url:")


def _affiliate_audit(store: str, url: str) -> dict[str, str]:
    store_value = (store or "").strip().lower()
    value = (url or "").strip()

    if not value:
        return {"severity": "broken", "reason": "Sem link afiliado salvo."}

    if store_value == "mercado livre":
        has_wid = "wid=" in value
        has_sid = "sid=affiliates" in value
        has_recos = "sid=recos" in value
        has_polycard = "polycard_client=affiliates" in value
        has_affiliate_profile = "affiliate-profile" in value
        has_matt = "matt_tool=" in value
        has_social = "/social/" in value
        if has_social or has_matt or has_wid or (has_wid and has_recos and has_affiliate_profile):
            return {"severity": "ok", "reason": "Link oficial Mercado Livre."}
        return {"severity": "broken", "reason": "Link ML sem marcador oficial."}

    if store_value == "shopee":
        if "an_" in value or "mmp_pid=" in value or "utm_medium=affiliates" in value:
            return {"severity": "ok", "reason": "Link Shopee com marcador afiliado visivel."}
        if "s.shopee.com.br/" in value:
            return {
                "severity": "ok",
                "reason": "Shortlink oficial da Shopee; os marcadores podem aparecer apenas apos o redirecionamento.",
            }
        return {"severity": "broken", "reason": "Link Shopee sem marcador afiliado visivel."}

    if store_value == "amazon":
        if "tag=" in value:
            return {"severity": "ok", "reason": "Link Amazon com tag."}
        return {"severity": "broken", "reason": "Link Amazon sem tag."}

    return {"severity": "suspect", "reason": "Loja sem regra de afiliado definida."}


def _site_base_url() -> str:
    return os.getenv("SITE_BASE_URL", "https://zeropreco.com.br").rstrip("/")


def _whatsapp_group_link() -> str:
    return (
        os.getenv("WHATSAPP_GROUP_LINK")
        or "https://chat.whatsapp.com/IavSEP6OPh5ISM4WHluOax?mode=gi_t"
    ).strip()


def _whatsapp_group_label() -> str:
    return (os.getenv("WHATSAPP_GROUP_LABEL") or "Grupo de WhatsApp").strip() or "Grupo de WhatsApp"


def _whatsapp_group_qr_url() -> str:
    configured = (os.getenv("WHATSAPP_GROUP_QR_URL") or "").strip()
    if configured:
        return configured
    return f"https://quickchart.io/qr?size=420&text={quote(_whatsapp_group_link(), safe='')}"


def _whatsapp_group_qr_file() -> Path:
    configured = (os.getenv("WHATSAPP_GROUP_QR_FILE") or "").strip()
    if configured:
        candidate = Path(configured)
        if not candidate.is_absolute():
            candidate = Path(__file__).resolve().parents[2] / candidate
        return candidate
    return Path(__file__).resolve().parents[2] / "assets" / "whatsapp-group-qr.png"


def _meta_api_base() -> str:
    version = (os.getenv("META_GRAPH_API_VERSION") or "v23.0").strip() or "v23.0"
    return f"https://graph.facebook.com/{version}"


def _meta_app_id() -> str:
    app_id = (os.getenv("META_APP_ID") or "").strip()
    if not app_id:
        raise ValueError("META_APP_ID nao preenchido no .env.")
    return app_id


def _meta_app_secret() -> str:
    app_secret = (os.getenv("META_APP_SECRET") or "").strip()
    if not app_secret:
        raise ValueError("META_APP_SECRET nao preenchido no .env.")
    return app_secret


def _meta_token() -> str:
    token = (os.getenv("META_ACCESS_TOKEN") or "").strip()
    if not token:
        raise ValueError("META_ACCESS_TOKEN nao preenchido no .env.")
    return token


def _write_env_updates(updates: dict[str, str]) -> None:
    if not ENV_FILE.exists():
        return

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


def _meta_debug_token(token: str) -> dict[str, Any]:
    app_access_token = f"{_meta_app_id()}|{_meta_app_secret()}"
    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"{_meta_api_base()}/debug_token",
            params={
                "input_token": token,
                "access_token": app_access_token,
            },
        )
        response.raise_for_status()
        return response.json().get("data", {})


def _exchange_for_long_lived_meta_token(token: str) -> dict[str, Any]:
    with httpx.Client(timeout=20) as client:
        response = client.get(
            "https://graph.facebook.com/oauth/access_token",
            params={
                "grant_type": "fb_exchange_token",
                "client_id": _meta_app_id(),
                "client_secret": _meta_app_secret(),
                "fb_exchange_token": token,
            },
        )
        response.raise_for_status()
        return response.json()


def _meta_user_token() -> str:
    token = _meta_token()
    try:
        debug = _meta_debug_token(token)
    except Exception:
        return token

    expires_at = int(debug.get("expires_at") or 0)
    now_ts = int(time.time())
    should_refresh = not bool(debug.get("is_valid")) or (expires_at and (expires_at - now_ts) <= META_REFRESH_WINDOW_SECONDS)
    if not should_refresh:
        return token

    try:
        refreshed = _exchange_for_long_lived_meta_token(token)
    except Exception:
        return token

    next_token = (refreshed.get("access_token") or "").strip()
    if not next_token:
        return token

    updates = {"META_ACCESS_TOKEN": next_token}
    if refreshed.get("expires_in"):
        updates["META_ACCESS_TOKEN_EXPIRES_IN"] = str(refreshed["expires_in"])
    _write_env_updates(updates)
    return next_token


def _meta_page_id() -> str:
    page_id = (os.getenv("META_PAGE_ID") or "").strip()
    if not page_id:
        raise ValueError("META_PAGE_ID nao preenchido no .env.")
    return page_id


def _meta_page_token() -> str:
    user_token = _meta_user_token()
    page_id = _meta_page_id()

    with httpx.Client(timeout=20) as client:
        response = client.get(
            f"{_meta_api_base()}/me/accounts",
            params={"access_token": user_token},
        )
        response.raise_for_status()
        data = response.json()

    for item in data.get("data", []):
        if str(item.get("id")) == page_id:
            page_token = (item.get("access_token") or "").strip()
            if page_token:
                return page_token

    raise ValueError(
        "Nao foi possivel derivar o token da pagina no /me/accounts. "
        "Verifique META_PAGE_ID e as permissoes do META_ACCESS_TOKEN."
    )


def _meta_instagram_account_id() -> str:
    account_id = (os.getenv("META_INSTAGRAM_BUSINESS_ACCOUNT_ID") or "").strip()
    if not account_id:
        raise ValueError("META_INSTAGRAM_BUSINESS_ACCOUNT_ID nao preenchido no .env.")
    return account_id


def _store_label(value: str) -> str:
    lowered = (value or "").strip().lower()
    mapping = {
        "mercado livre": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "tiktok": "TikTok Shop",
    }
    return mapping.get(lowered, (value or "Loja").strip() or "Loja")


def _normalize_key(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def _category_label(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() == "geral":
        return "ofertas"
    mapped = CATEGORY_LABELS.get(_normalize_key(raw))
    if mapped:
        return mapped
    return raw.replace("-", " ").replace("_", " ")


def _diversify_offer_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    seen_stores: set[str] = set()
    seen_categories: set[str] = set()
    preferred_store_targets = {
        _normalize_key("Amazon"): 2 if limit >= 6 else 1,
        _normalize_key("Shopee"): 2 if limit >= 6 else 1,
    }

    def include(row: dict[str, Any]) -> None:
        offer_id = int(row["id"])
        if offer_id in selected_ids or len(selected) >= limit:
            return
        selected.append(row)
        selected_ids.add(offer_id)
        seen_stores.add(_normalize_key(_store_label(row.get("loja") or "")))
        seen_categories.add(_normalize_key(_category_label(row.get("categoria") or "")))

    grouped_by_store: dict[str, list[dict[str, Any]]] = {}
    store_order: list[str] = []
    for row in rows:
        store_key = _normalize_key(_store_label(row.get("loja") or ""))
        if store_key not in grouped_by_store:
            grouped_by_store[store_key] = []
            store_order.append(store_key)
        grouped_by_store[store_key].append(row)

    # Guarantee minimum presence for Amazon and Shopee when inventory exists.
    for store_key, target in preferred_store_targets.items():
        bucket = grouped_by_store.get(store_key) or []
        picked = 0
        while bucket and picked < target and len(selected) < limit:
            while bucket and int(bucket[0]["id"]) in selected_ids:
                bucket.pop(0)
            if not bucket:
                break
            include(bucket.pop(0))
            picked += 1

    # First round: bring one strong offer from each store before repeating.
    while len(selected) < limit:
        progressed = False
        for store_key in store_order:
            bucket = grouped_by_store.get(store_key) or []
            while bucket and int(bucket[0]["id"]) in selected_ids:
                bucket.pop(0)
            if not bucket:
                continue
            include(bucket.pop(0))
            progressed = True
            if len(selected) >= limit:
                return selected
        if not progressed:
            break

    for row in rows:
        store_key = _normalize_key(_store_label(row.get("loja") or ""))
        if store_key not in seen_stores:
            include(row)
        if len(selected) >= limit:
            return selected

    for row in rows:
        category_key = _normalize_key(_category_label(row.get("categoria") or ""))
        if category_key not in seen_categories:
            include(row)
        if len(selected) >= limit:
            return selected

    for row in rows:
        include(row)
        if len(selected) >= limit:
            return selected

    return selected


def _money(value: Any) -> str:
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _discount_percent(price: Any, old_price: Any) -> int:
    current = float(price or 0)
    previous = float(old_price or 0)
    if current <= 0 or previous <= current:
        return 0
    return int(round(((previous - current) / previous) * 100))


def _offer_discount_percent(offer: dict[str, Any]) -> int:
    if offer.get("desconto_percentual") is not None:
        return int(offer.get("desconto_percentual") or 0)
    return _discount_percent(offer.get("preco"), offer.get("preco_antigo"))


def _offer_highlights(offer: dict[str, Any]) -> list[str]:
    details: list[str] = []
    category = _category_label(offer.get("categoria") or "")
    if category:
        details.append(f"Categoria: {category}")
    discount = _offer_discount_percent(offer)
    if discount > 0:
        details.append(f"Desconto: {discount}% OFF")
    if offer.get("preco_pix") is not None:
        details.append(f"No Pix: {_money(offer['preco_pix'])}")
    if offer.get("preco_outros_meios") is not None:
        details.append(f"Outros meios: {_money(offer['preco_outros_meios'])}")
    installments = (offer.get("parcelas_texto") or "").strip()
    if installments:
        details.append(f"Parcelamento: {installments}")
    shipping = (offer.get("frete_texto") or "").strip()
    if shipping:
        details.append(f"Frete: {shipping}")
    rating = offer.get("avaliacao_nota")
    rating_count = offer.get("avaliacao_total")
    if rating is not None and rating_count:
        details.append(f"Avaliacao: {float(rating):.1f}/5 ({int(rating_count)})")
    elif rating is not None:
        details.append(f"Avaliacao: {float(rating):.1f}/5")
    promotion = (offer.get("promocao_texto") or "").strip()
    if promotion:
        details.append(f"Promocao: {promotion}")
    coupon = (offer.get("cupom") or "").strip()
    if coupon:
        details.append(f"Cupom: {coupon}")
    return details


def _offer_url(slug: str) -> str:
    return f"{_site_base_url()}/oferta.php?slug={slug}"


def _cta_url(slug: str) -> str:
    return f"{_site_base_url()}/oferta.php?slug={slug}&go=1"


def _destination_url(offer: dict[str, Any]) -> str:
    preferred = (offer.get("url_afiliado") or "").strip()
    if preferred:
        return preferred
    return _cta_url(offer["slug"])


def _site_offer_url(offer: dict[str, Any]) -> str:
    return _offer_url(offer["slug"])


def _display_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").replace("www.", "")
    path = (parsed.path or "").rstrip("/")
    if path and path != "/":
        compact_path = path[:28] + "..." if len(path) > 31 else path
        return f"{host}{compact_path}"
    if parsed.query:
        return host or url[:36]
    return host or url[:36]


def _headline_for_offer(offer: dict[str, Any]) -> str:
    return f"{offer['titulo']} por {_money(offer['preco'])}"


def _caption_for_offer(offer: dict[str, Any]) -> str:
    price = _money(offer["preco"])
    store = _store_label(offer["loja"])
    destination_url = _destination_url(offer)
    site_offer_url = _site_offer_url(offer)
    has_direct_store_link = bool((offer.get("url_afiliado") or "").strip())

    lead = f"{offer['titulo']}\n{price} na {store}"
    details = _offer_highlights(offer)

    lines = [lead]
    lines.extend(details[:7])
    lines.extend([
        "",
        "Abrir direto na loja:" if has_direct_store_link else "Veja o produto no site:",
        destination_url,
        "Ver no site:" if has_direct_store_link else "Oferta no site:",
        site_offer_url,
        "",
        f"{_whatsapp_group_label()}:",
        _whatsapp_group_link(),
        "",
        "#ofertas #promocao #zeropreco",
    ])
    return "\n".join(lines)


def _story_caption_for_offer(offer: dict[str, Any]) -> str:
    store = _store_label(offer["loja"])
    destination_url = _destination_url(offer)
    site_offer_url = _site_offer_url(offer)
    has_direct_store_link = bool((offer.get("url_afiliado") or "").strip())
    parts = [f"{offer['titulo']}", f"{_money(offer['preco'])} na {store}"]
    parts.extend(_offer_highlights(offer)[:4])
    parts.append("Abrir direto na loja:" if has_direct_store_link else "Ver produto no site:")
    parts.append(destination_url)
    parts.append("Ver no site:")
    parts.append(site_offer_url)
    return "\n".join(parts)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()
    cleaned = cleaned[:80].rstrip("-")
    return cleaned or "oferta"


def _load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.extend(
            [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _wrap_text(value: str, limit: int) -> list[str]:
    words = (value or "").split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if len(candidate) <= limit:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _split_text(value: str, limit: int) -> list[str]:
    content = (value or "").strip()
    if not content:
        return []
    return [content[index:index + limit] for index in range(0, len(content), limit)]


def _truncate_text(value: str, limit: int) -> str:
    content = (value or "").strip()
    if len(content) <= limit:
        return content
    return content[: max(0, limit - 3)].rstrip(" -|,.;") + "..."


def _draw_story_chip(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
    fill: str,
    text_fill: str,
    height: int = 46,
) -> int:
    content = _truncate_text(text, 58)
    bbox = draw.textbbox((0, 0), content, font=font)
    width = min(max_width, (bbox[2] - bbox[0]) + 44)
    draw.rounded_rectangle((x, y, x + width, y + height), radius=18, fill=fill)
    draw.text((x + 18, y + 7), content, font=font, fill=text_fill)
    return y + height + 14


def _draw_story_link_sticker(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    host: str,
    width: int = 430,
) -> None:
    sticker_box = (x, y, x + width, y + 68)
    icon_box = (x + 14, y + 14, x + 54, y + 54)
    draw.rounded_rectangle(sticker_box, radius=24, fill="#ffffff")
    draw.rounded_rectangle(icon_box, radius=20, fill="#e7f0ff")
    icon_font = _load_font(16, bold=True)
    label_font = _load_font(22, bold=True)
    host_font = _load_font(18)
    draw.text((x + 19, y + 24), "URL", font=icon_font, fill="#1463ff")
    draw.text((x + 70, y + 13), "Link da loja aqui", font=label_font, fill="#0b2d78")
    draw.text((x + 70, y + 38), _truncate_text(host, 30), font=host_font, fill="#5a6f99")


def _fit_remote_product_image(url: str, size: tuple[int, int]) -> Image.Image | None:
    image_url = (url or "").strip()
    if not image_url:
        return None
    try:
        with httpx.Client(timeout=25, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
        with Image.open(BytesIO(response.content)) as source:
            converted = source.convert("RGB")
            return ImageOps.fit(converted, size, method=Image.Resampling.LANCZOS)
    except Exception:  # noqa: BLE001
        return None


def _decode_offer_url_list(value: Any) -> list[str]:
    candidates: list[Any] = []
    if isinstance(value, list):
        candidates = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        if isinstance(decoded, list):
            candidates = decoded
        else:
            candidates = [raw]

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


def _offer_image_gallery_urls(offer: dict[str, Any], *, limit: int = 6) -> list[str]:
    gallery = _decode_offer_url_list(offer.get("imagem_urls") or offer.get("image_urls") or offer.get("imagem_urls_json"))
    primary = str(offer.get("imagem_url") or offer.get("image_url") or "").strip()
    if primary and primary not in gallery:
        gallery.insert(0, primary)
    if not gallery and primary:
        gallery = [primary]
    return gallery[: max(1, limit)]


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _render_reel_frame(base_image: Image.Image, progress: float) -> Image.Image:
    width, height = base_image.size
    zoom = 1.0 + (0.04 * max(0.0, min(progress, 1.0)))
    resized = base_image.resize((int(width * zoom), int(height * zoom)), Image.Resampling.LANCZOS)
    return ImageOps.fit(resized, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))


def _default_reel_creative(offer: dict[str, Any]) -> dict[str, Any]:
    title = _truncate_text(str(offer.get("titulo") or "Oferta"), 72)
    price = _money(offer.get("preco"))
    discount = _offer_discount_percent(offer)
    pix_price = offer.get("preco_pix")
    installments = str(offer.get("parcelas_texto") or "").strip()
    shipping = str(offer.get("frete_texto") or "").strip()
    detail = ""
    if pix_price not in (None, "", 0, 0.0):
        detail = f"No Pix: {_money(pix_price)}"
    elif installments:
        detail = installments
    elif shipping:
        detail = shipping
    else:
        detail = "Confira os detalhes no link da oferta."
    price_line = price + (f" | {discount}% OFF" if discount > 0 else "")
    return {
        "scene_overlays": [
            {"eyebrow": "ACHADO", "headline": title, "subline": price, "sticker": "OFERTA"},
            {"eyebrow": "DESTAQUE", "headline": price_line, "subline": detail, "sticker": "PROMO"},
            {"eyebrow": "CTA", "headline": "Confira a oferta completa", "subline": "Abra o link e veja o valor atualizado.", "sticker": "VER AGORA"},
        ]
    }


def _scene_animation_alpha(progress: float) -> float:
    enter = min(1.0, max(0.0, progress / 0.18))
    exit = min(1.0, max(0.0, (1.0 - progress) / 0.14))
    return max(0.0, min(enter, exit))


def _draw_overlay_text(
    draw: ImageDraw.ImageDraw,
    *,
    x: int,
    y: int,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    shadow_fill: tuple[int, int, int, int],
    line_spacing: int = 10,
) -> int:
    current_y = y
    for line in _wrap_text(_clean_text(text), 22):
        if not line:
            continue
        draw.text((x + 3, current_y + 3), line, font=font, fill=shadow_fill)
        draw.text((x, current_y), line, font=font, fill=fill)
        bbox = draw.textbbox((x, current_y), line, font=font)
        current_y = bbox[3] + line_spacing
    return current_y


def _apply_reel_overlay(
    frame: Image.Image,
    offer: dict[str, Any],
    scene: dict[str, Any],
    *,
    scene_progress: float,
    scene_index: int,
    total_scenes: int,
) -> Image.Image:
    alpha_factor = _scene_animation_alpha(scene_progress)
    if alpha_factor <= 0:
        return frame

    overlay = Image.new("RGBA", frame.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = frame.size

    top_panel = (54, 82, width - 54, 540)
    bottom_panel = (54, height - 280, width - 54, height - 92)
    panel_fill = (8, 24, 66, int(165 * alpha_factor))
    panel_outline = (142, 186, 255, int(185 * alpha_factor))
    draw.rounded_rectangle(top_panel, radius=36, fill=panel_fill, outline=panel_outline, width=3)
    draw.rounded_rectangle(bottom_panel, radius=34, fill=(255, 255, 255, int(215 * alpha_factor)))

    badge_fill = (255, 210, 82, int(240 * alpha_factor))
    badge_box = (82, 108, 360, 164)
    draw.rounded_rectangle(badge_box, radius=20, fill=badge_fill)
    badge_font = _load_font(24, bold=True)
    draw.text((104, 122), _truncate_text(str(scene.get("eyebrow") or _category_label(offer.get("categoria") or "")), 22), font=badge_font, fill=(33, 47, 74, int(255 * alpha_factor)))

    sticker_text = _truncate_text(str(scene.get("sticker") or "OFERTA"), 20)
    sticker_font = _load_font(22, bold=True)
    sticker_bbox = draw.textbbox((0, 0), sticker_text, font=sticker_font)
    sticker_width = (sticker_bbox[2] - sticker_bbox[0]) + 42
    sticker_box = (width - 82 - sticker_width, 108, width - 82, 164)
    draw.rounded_rectangle(sticker_box, radius=20, fill=(255, 255, 255, int(228 * alpha_factor)))
    draw.text((sticker_box[0] + 21, 122), sticker_text, font=sticker_font, fill=(11, 45, 120, int(255 * alpha_factor)))

    enter_offset = int((1.0 - alpha_factor) * 34)
    headline_font = _load_font(52, bold=True)
    subline_font = _load_font(28, bold=False)
    current_y = _draw_overlay_text(
        draw,
        x=82,
        y=194 + enter_offset,
        text=str(scene.get("headline") or ""),
        font=headline_font,
        fill=(255, 255, 255, int(255 * alpha_factor)),
        shadow_fill=(0, 0, 0, int(120 * alpha_factor)),
        line_spacing=14,
    )
    _draw_overlay_text(
        draw,
        x=82,
        y=current_y + 4,
        text=str(scene.get("subline") or ""),
        font=subline_font,
        fill=(225, 236, 255, int(245 * alpha_factor)),
        shadow_fill=(0, 0, 0, int(110 * alpha_factor)),
        line_spacing=8,
    )

    progress_text = f"{scene_index + 1}/{max(1, total_scenes)}"
    progress_font = _load_font(24, bold=True)
    draw.text((86, height - 244), progress_text, font=progress_font, fill=(11, 45, 120, int(230 * alpha_factor)))
    cta_font = _load_font(34, bold=True)
    cta_line = _truncate_text(str(scene.get("headline") if scene_index == total_scenes - 1 else scene.get("subline") or "Abra o link da oferta"), 48)
    draw.text((86, height - 200), cta_line, font=cta_font, fill=(11, 45, 120, int(255 * alpha_factor)))

    if scene_index == total_scenes - 1:
        pulse = 0.86 + (0.14 * ((math.sin(scene_progress * math.pi * 2.0) + 1.0) / 2.0))
        brand_label = _truncate_text(str(scene.get("brand") or os.getenv("SHOPEE_VIDEO_BRAND_NAME") or "ZERO PRECO"), 18)
        button_label = _truncate_text(str(scene.get("button_label") or "ABRIR AGORA"), 18)
        button_width = int(320 * pulse)
        button_height = 86
        button_x1 = width - 86 - button_width
        button_y1 = height - 242
        button_x2 = width - 86
        button_y2 = button_y1 + button_height
        draw.rounded_rectangle((button_x1, button_y1, button_x2, button_y2), radius=26, fill=(34, 98, 255, int(245 * alpha_factor)))
        draw.rounded_rectangle((button_x1, button_y1, button_x2, button_y2), radius=26, outline=(255, 255, 255, int(220 * alpha_factor)), width=3)
        button_font = _load_font(28, bold=True)
        brand_font = _load_font(20, bold=True)
        draw.text((button_x1 + 28, button_y1 + 17), button_label, font=button_font, fill=(255, 255, 255, int(255 * alpha_factor)))
        draw.text((button_x1 + 28, button_y1 + 49), brand_label, font=brand_font, fill=(220, 235, 255, int(245 * alpha_factor)))

    bar_x1 = 86
    bar_x2 = width - 86
    bar_y1 = height - 132
    bar_y2 = height - 112
    draw.rounded_rectangle((bar_x1, bar_y1, bar_x2, bar_y2), radius=10, fill=(210, 224, 255, int(255 * alpha_factor)))
    filled_ratio = min(1.0, max(0.12, (scene_index + scene_progress) / max(1, total_scenes)))
    filled_x2 = int(bar_x1 + ((bar_x2 - bar_x1) * filled_ratio))
    draw.rounded_rectangle((bar_x1, bar_y1, filled_x2, bar_y2), radius=10, fill=(34, 98, 255, int(255 * alpha_factor)))

    return Image.alpha_composite(frame.convert("RGBA"), overlay).convert("RGB")


def _fit_local_product_image(path: Path, size: tuple[int, int]) -> Image.Image | None:
    if not path.is_file():
        return None
    try:
        with Image.open(path) as source:
            converted = source.convert("RGB")
            return ImageOps.fit(converted, size, method=Image.Resampling.LANCZOS)
    except Exception:  # noqa: BLE001
        return None


def _build_story_canvas(
    offer: dict[str, Any],
    *,
    product_image: Image.Image | None = None,
    show_placeholder: bool = True,
    show_brand_label: bool = True,
    vertical_shift: int = 0,
) -> dict[str, Any]:
    destination_url = _destination_url(offer)
    destination_host = _display_url(destination_url)
    destination_label = "Acesse no site"
    destination_label_secondary = "zeropreco.com.br"
    whatsapp_group_label = _whatsapp_group_label()
    whatsapp_group_link = _whatsapp_group_link()
    whatsapp_group_qr = _fit_local_product_image(_whatsapp_group_qr_file(), (220, 220))
    if whatsapp_group_qr is None:
        whatsapp_group_qr = _fit_remote_product_image(_whatsapp_group_qr_url(), (220, 220))

    image = Image.new("RGB", (1080, 1920), "#0a2a67")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1080, 1920), fill="#0a2a67")
    draw.ellipse((700, 80, 1050, 430), fill="#1b4fc3")
    draw.ellipse((-120, 1450, 260, 1830), fill="#12398f")
    draw.rounded_rectangle((54, 54, 1026, 1866), radius=42, outline="#2f65db", width=4)

    title_font = _load_font(56, bold=True)
    price_font = _load_font(96, bold=True)
    old_price_font = _load_font(34)
    label_font = _load_font(30, bold=True)
    text_font = _load_font(32)
    cta_font = _load_font(34, bold=True)
    cta_small_font = _load_font(26, bold=True)
    micro_font = _load_font(22)
    domain_font = _load_font(40, bold=True)

    if show_brand_label:
        draw.text((80, 120 + vertical_shift), "ZERO PRECO", font=label_font, fill="#dbe7ff")

    title_lines = _wrap_text(offer["titulo"], 23)[:3]
    y = 250 + vertical_shift
    for line in title_lines:
        draw.text((80, y), line, font=title_font, fill="#f4f7fb")
        y += 68

    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))

    price_y = y + 34
    draw.text((80, price_y), _money(offer["preco"]), font=price_font, fill="#ffffff")

    info_y = price_y + 116
    if offer.get("preco_antigo"):
        old_price_text = f"De {_money(offer['preco_antigo'])}"
        draw.text((80, info_y), old_price_text, font=old_price_font, fill="#b9c8e6")
        old_price_bbox = draw.textbbox((80, info_y), old_price_text, font=old_price_font)
        strike_y = (old_price_bbox[1] + old_price_bbox[3]) / 2
        draw.line((old_price_bbox[0], strike_y, old_price_bbox[2], strike_y), fill="#ffb7b7", width=3)
        info_y += 54

    installments_text = normalize_installments_text(offer.get("parcelas_texto"))
    if installments_text:
        info_y = _draw_story_chip(
            draw,
            x=80,
            y=info_y,
            text=f"Parcelamento: {installments_text}",
            font=_load_font(24, bold=True),
            max_width=820,
            fill="#163d95",
            text_fill="#eef4ff",
        )
    elif offer.get("preco_pix") is not None:
        info_y = _draw_story_chip(
            draw,
            x=80,
            y=info_y,
            text=f"No Pix: {_money(offer['preco_pix'])}",
            font=_load_font(24, bold=True),
            max_width=640,
            fill="#163d95",
            text_fill="#eef4ff",
        )

    coupon_text = (offer.get("cupom") or "").strip()
    promo_text = clean_offer_highlight_text(offer.get("promocao_texto"), discount=discount, installments=installments_text)
    banner_text = ""
    banner_fill = "#113885"
    banner_text_fill = "#f4f7fb"
    if coupon_text:
        banner_text = f"Cupom: {coupon_text}"
        banner_fill = "#fff2c2"
        banner_text_fill = "#6b4700"
    elif promo_text:
        banner_text = promo_text
    if banner_text:
        info_y = _draw_story_chip(
            draw,
            x=80,
            y=info_y,
            text=banner_text,
            font=_load_font(24, bold=True),
            max_width=860,
            fill=banner_fill,
            text_fill=banner_text_fill,
            height=52,
        )

    commerce_lines: list[str] = []
    if (offer.get("frete_texto") or "").strip():
        commerce_lines.append(f"Frete: {str(offer.get('frete_texto')).strip()}")
    rating = offer.get("avaliacao_nota")
    rating_count = offer.get("avaliacao_total")
    if rating is not None and rating_count:
        commerce_lines.append(f"Avaliacao: {float(rating):.1f}/5 ({int(rating_count)})")
    elif rating is not None:
        commerce_lines.append(f"Avaliacao: {float(rating):.1f}/5")

    for line in commerce_lines[:1]:
        info_y = _draw_story_chip(
            draw,
            x=80,
            y=info_y,
            text=line,
            font=_load_font(24, bold=True),
            max_width=760,
            fill="#163d95",
            text_fill="#eef4ff",
        )

    draw.text(
        (80, info_y + 4),
        f"{_store_label(offer['loja'])} | {_category_label(offer['categoria'])}",
        font=text_font,
        fill="#dbe7ff",
    )

    product_top = max(780 + vertical_shift, info_y + 56)
    product_bottom = product_top + 520
    product_card_box = (80, product_top, 1000, product_bottom)
    draw.rounded_rectangle(product_card_box, radius=36, fill="#f8fbff")
    product_inner_box = (120, product_top + 40, 960, product_top + 510)
    if product_image is not None:
        image.paste(product_image, (product_inner_box[0], product_inner_box[1]))
    else:
        draw.rounded_rectangle(product_inner_box, radius=28, fill="#d9e5ff")
    draw.rounded_rectangle(product_inner_box, radius=28, outline="#d7e4ff", width=4)
    if product_image is None and show_placeholder:
        draw.text((180, product_top + 255), "Imagem do produto", font=cta_font, fill="#0b2d78")

    _draw_story_link_sticker(
        draw,
        x=142,
        y=product_bottom - 34,
        host=destination_host,
        width=430,
    )

    footer_top = product_bottom + 38
    draw.rounded_rectangle((80, footer_top, 580, footer_top + 170), radius=32, fill="#ffffff")
    draw.rounded_rectangle((104, footer_top + 24, 556, footer_top + 146), radius=26, fill="#e8f0ff")
    draw.text((136, footer_top + 34), destination_label, font=cta_small_font, fill="#0b2d78")
    draw.text((136, footer_top + 78), destination_label_secondary, font=cta_font, fill="#0b2d78")

    qr_outer_box = (686, footer_top + 30, 880, footer_top + 224)
    qr_inner_box = (694, footer_top + 38, 872, footer_top + 216)
    qr_label = "Grupo WhatsApp"
    qr_label_bbox = draw.textbbox((0, 0), qr_label, font=cta_small_font)
    qr_label_width = qr_label_bbox[2] - qr_label_bbox[0]
    qr_label_x = qr_outer_box[0] + ((qr_outer_box[2] - qr_outer_box[0] - qr_label_width) / 2)
    draw.text((qr_label_x, footer_top - 8), qr_label, font=cta_small_font, fill="#ffffff")
    draw.rounded_rectangle(qr_outer_box, radius=18, fill="#f7fbff", outline="#8fb9ff", width=3)
    if whatsapp_group_qr is not None:
        qr_image = ImageOps.fit(whatsapp_group_qr, (178, 178), method=Image.Resampling.LANCZOS)
        qr_x = qr_inner_box[0] + ((qr_inner_box[2] - qr_inner_box[0] - qr_image.width) // 2)
        qr_y = qr_inner_box[1] + ((qr_inner_box[3] - qr_inner_box[1] - qr_image.height) // 2)
        image.paste(qr_image, (qr_x, qr_y))
    else:
        draw.rounded_rectangle(qr_inner_box, radius=18, fill="#d9e5ff")
        qr_placeholder_bbox = draw.textbbox((0, 0), "QR", font=cta_font)
        qr_placeholder_width = qr_placeholder_bbox[2] - qr_placeholder_bbox[0]
        qr_placeholder_height = qr_placeholder_bbox[3] - qr_placeholder_bbox[1]
        qr_placeholder_x = qr_inner_box[0] + ((qr_inner_box[2] - qr_inner_box[0] - qr_placeholder_width) / 2)
        qr_placeholder_y = qr_inner_box[1] + ((qr_inner_box[3] - qr_inner_box[1] - qr_placeholder_height) / 2) - 4
        draw.text((qr_placeholder_x, qr_placeholder_y), "QR", font=cta_font, fill="#0b2d78")

    link_top = footer_top + 260
    draw.text((80, link_top), destination_host, font=domain_font, fill="#ffffff")
    draw.text(
        (80, link_top + 108),
        "Siga para a loja parceira.",
        font=text_font,
        fill="#dbe7ff",
    )

    return {
        "image": image,
        "destination_url": destination_url,
        "destination_host": destination_host,
        "product_inner_box": product_inner_box,
        "product_border_radius": 28,
    }


def generate_story_asset(offer: dict[str, Any]) -> dict[str, Any]:
    filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}.jpg"
    destination = ensure_stories_dir() / filename
    product_image = _fit_remote_product_image(offer.get("imagem_url"), (840, 470))
    story_canvas = _build_story_canvas(offer, product_image=product_image)
    image = story_canvas["image"]

    image.save(destination, format="JPEG", quality=92, optimize=True)
    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": story_public_url(filename),
        "caption": _story_caption_for_offer(offer),
        "destination_url": story_canvas["destination_url"],
    }


def generate_story_video_asset(
    offer: dict[str, Any],
    source_video_path: str,
    *,
    max_duration_seconds: int = 12,
) -> dict[str, Any]:
    source_path = Path(source_video_path)
    if not source_path.is_file():
        raise ValueError("Arquivo de video de origem nao encontrado para story.")

    poster_asset = generate_story_asset(offer)
    story_canvas = _build_story_canvas(offer, product_image=None, show_placeholder=False)
    base_image = story_canvas["image"].convert("RGB")
    product_inner_box = tuple(int(value) for value in story_canvas["product_inner_box"])
    x1, y1, x2, y2 = product_inner_box
    product_size = (x2 - x1, y2 - y1)
    border_radius = int(story_canvas["product_border_radius"])

    mask = Image.new("L", product_size, 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, product_size[0], product_size[1]), radius=border_radius, fill=255)

    filename = Path(poster_asset["filename"]).stem + "-story-video.mp4"
    destination = ensure_stories_dir() / filename

    _prefer_system_ffmpeg_for_imageio()

    metadata_reader = imageio.get_reader(str(source_path))
    try:
        metadata = metadata_reader.get_meta_data() or {}
    finally:
        metadata_reader.close()
    fps = float(metadata.get("fps") or 24)
    if fps <= 0:
        fps = 24
    fps = min(max(fps, 12), 30)
    max_frames = max(1, int(fps * max_duration_seconds))

    rendered_frames = 0
    selected_codec = ""
    errors: list[str] = []
    for codec in _story_video_codec_candidates():
        destination.unlink(missing_ok=True)
        reader = imageio.get_reader(str(source_path))
        writer = imageio.get_writer(
            str(destination),
            fps=fps,
            codec=codec,
            pixelformat="yuv420p",
            macro_block_size=None,
            ffmpeg_log_level="warning",
            output_params=_story_video_output_params(codec=codec),
        )
        rendered_frames = 0
        write_error = ""
        try:
            for frame_data in reader:
                frame_image = Image.fromarray(frame_data).convert("RGB")
                fitted = ImageOps.fit(frame_image, product_size, method=Image.Resampling.LANCZOS)
                canvas = base_image.copy()
                canvas.paste(fitted, (x1, y1), mask)
                frame_draw = ImageDraw.Draw(canvas)
                frame_draw.rounded_rectangle(product_inner_box, radius=border_radius, outline="#d7e4ff", width=4)
                writer.append_data(np.asarray(canvas))
                rendered_frames += 1
                if rendered_frames >= max_frames:
                    break
        except Exception as exc:  # noqa: BLE001
            write_error = str(exc)
        finally:
            close_error = _close_imageio_writer_safely(writer)
            reader.close()
        if close_error:
            write_error = close_error if write_error == "" else f"{write_error} | close: {close_error}"
        if write_error:
            errors.append(f"{codec}: {write_error}")
        if rendered_frames > 0 and destination.is_file():
            selected_codec = codec
            break

    if rendered_frames <= 0 or not destination.is_file():
        destination.unlink(missing_ok=True)
        details = " | ".join(errors[:3]).strip()
        suffix = f" Detalhes: {details}" if details else ""
        raise ValueError(f"Nao foi possivel renderizar frames do video para o story.{suffix}")

    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": story_public_url(filename),
        "caption": _story_caption_for_offer(offer),
        "destination_url": story_canvas["destination_url"],
        "poster_url": poster_asset["public_url"],
        "video_codec": selected_codec,
    }


def generate_reel_asset(
    offer: dict[str, Any],
    *,
    duration_seconds: float = 6,
    fps: int = 24,
    creative: dict[str, Any] | None = None,
) -> dict[str, Any]:
    stories_dir = ensure_stories_dir()
    poster_filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}-reel-poster.jpg"
    poster_path = stories_dir / poster_filename
    gallery_urls = _offer_image_gallery_urls(offer)
    reel_frames: list[Image.Image] = []
    for image_url in gallery_urls:
        product_image = _fit_remote_product_image(image_url, (840, 470))
        if product_image is None:
            continue
        reel_canvas = _build_story_canvas(
            offer,
            product_image=product_image,
            show_brand_label=False,
            vertical_shift=-70,
        )
        reel_frames.append(reel_canvas["image"].convert("RGB"))

    if not reel_frames:
        fallback_image = _fit_remote_product_image(offer.get("imagem_url"), (840, 470))
        reel_canvas = _build_story_canvas(
            offer,
            product_image=fallback_image,
            show_brand_label=False,
            vertical_shift=-70,
        )
        reel_frames.append(reel_canvas["image"].convert("RGB"))

    base_image = reel_frames[0]
    base_image.save(poster_path, format="JPEG", quality=92, optimize=True)

    filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}-reel.mp4"
    destination = stories_dir / filename
    normalized_duration = max(1.5, float(duration_seconds or 0))
    total_frames = max(1, int(round(normalized_duration * fps)))
    resolved_creative = creative or _default_reel_creative(offer)
    scenes = list(resolved_creative.get("scene_overlays") or []) or list(_default_reel_creative(offer).get("scene_overlays") or [])

    _prefer_system_ffmpeg_for_imageio()

    selected_codec = ""
    errors: list[str] = []
    for codec in _story_video_codec_candidates():
        destination.unlink(missing_ok=True)
        writer = imageio.get_writer(
            str(destination),
            fps=fps,
            codec=codec,
            pixelformat="yuv420p",
            macro_block_size=None,
            ffmpeg_log_level="warning",
            output_params=_story_video_output_params(codec=codec),
        )
        write_error = ""
        try:
            for frame_index in range(total_frames):
                if len(reel_frames) == 1:
                    progress = frame_index / max(total_frames - 1, 1)
                    frame = _render_reel_frame(reel_frames[0], progress)
                    current_scene_index = min(int(progress * len(scenes)), len(scenes) - 1)
                    scene = scenes[current_scene_index]
                    scene_progress = (progress * len(scenes)) % 1.0
                else:
                    timeline = (frame_index / max(total_frames - 1, 1)) * len(reel_frames)
                    segment_index = min(int(timeline), len(reel_frames) - 1)
                    segment_progress = timeline - segment_index
                    current_frame = _render_reel_frame(reel_frames[segment_index], segment_progress)
                    transition_start = 0.72
                    if segment_index < len(reel_frames) - 1 and segment_progress >= transition_start:
                        blend = min(1.0, (segment_progress - transition_start) / (1.0 - transition_start))
                        next_frame = _render_reel_frame(reel_frames[segment_index + 1], max(0.0, segment_progress - transition_start))
                        frame = Image.blend(current_frame, next_frame, blend)
                    else:
                        frame = current_frame
                    current_scene_index = min(segment_index, len(scenes) - 1)
                    scene = scenes[current_scene_index]
                    scene_progress = segment_progress
                frame = _apply_reel_overlay(
                    frame,
                    offer,
                    scene,
                    scene_progress=scene_progress,
                    scene_index=current_scene_index,
                    total_scenes=len(scenes),
                )
                writer.append_data(np.asarray(frame))
        except Exception as exc:  # noqa: BLE001
            write_error = str(exc)
        finally:
            close_error = _close_imageio_writer_safely(writer)
        if close_error:
            write_error = close_error if write_error == "" else f"{write_error} | close: {close_error}"
        if write_error:
            errors.append(f"{codec}: {write_error}")
        if destination.is_file():
            selected_codec = codec
            break

    if not destination.is_file():
        details = " | ".join(errors[:3]).strip()
        suffix = f" Detalhes: {details}" if details else ""
        raise ValueError(f"Nao foi possivel gerar o reel em video.{suffix}")

    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": story_public_url(filename),
        "caption": _story_caption_for_offer(offer),
        "destination_url": _destination_url(offer),
        "poster_url": story_public_url(poster_filename),
        "gallery_count": len(reel_frames),
        "scene_count": len(scenes),
        "video_codec": selected_codec,
        "duration_seconds": round(normalized_duration, 2),
    }


def download_source_video_asset(offer: dict[str, Any], video_url: str) -> dict[str, Any]:
    normalized_url = str(video_url or "").strip()
    if not normalized_url.startswith(("http://", "https://")):
        raise ValueError("URL do video de origem invalida para download.")

    stories_dir = ensure_stories_dir()
    slug = re.sub(r"[^a-z0-9-]+", "-", str(offer.get("slug") or "oferta").strip().lower()).strip("-") or "oferta"
    parsed = urlparse(normalized_url)
    extension = Path(parsed.path or "").suffix.lower()
    if extension not in {".mp4", ".mov", ".m4v", ".webm"}:
        extension = ".mp4"
    url_hash = sha1(normalized_url.encode("utf-8")).hexdigest()[:10]
    filename = f"offer-{slug}-source-{url_hash}{extension}"
    destination = stories_dir / filename

    with httpx.Client(timeout=90, follow_redirects=True) as client:
        response = client.get(
            normalized_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/132.0.0.0 Safari/537.36"
                ),
                "Referer": str(offer.get("url_afiliado") or normalized_url),
            },
        )
        response.raise_for_status()
        content = response.content

    if not content:
        raise ValueError("Download do video da Shopee retornou arquivo vazio.")

    destination.write_bytes(content)

    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "source_url": normalized_url,
        "public_url": story_public_url(filename),
    }


def build_meta_post_previews(
    db,
    limit: int = 12,
    offer_ids: list[int] | None = None,
    include_story_assets: bool = True,
    include_square_card_assets: bool = False,
    search_query: str | None = None,
    store_filter: str | None = None,
) -> list[dict[str, Any]]:
    ensure_dashboard_tables(db)
    capped_limit = max(1, min(limit, 200))
    fetch_limit = max(capped_limit, len(offer_ids or []), 160)
    normalized_query = (search_query or "").strip()
    normalized_store = (store_filter or "").strip()
    if offer_ids:
        rows = db.execute(
            SELECT_OFFERS_BY_IDS_SQL,
            {"offer_ids": [int(offer_id) for offer_id in offer_ids]},
        ).mappings().all()
        selected_map = {int(row["id"]): row for row in rows}
        rows = [dict(selected_map[offer_id]) for offer_id in offer_ids if int(offer_id) in selected_map][:capped_limit]
    else:
        eligible_rows: list[dict[str, Any]] = []
        seen_offer_ids: set[int] = set()
        max_scan_batches = 8
        for batch_index in range(max_scan_batches):
            params = {
                "limit": fetch_limit,
                "offset": batch_index * fetch_limit,
                "store_filter": normalized_store,
                "search_query": normalized_query,
                "search_like": f"%{normalized_query}%",
            }
            batch_rows = db.execute(SELECT_TOP_OFFERS_SQL, params).mappings().all()
            if not batch_rows:
                break
            for row in batch_rows:
                offer_id = int(row["id"])
                if offer_id in seen_offer_ids:
                    continue
                seen_offer_ids.add(offer_id)
                if _affiliate_audit(str(row.get("loja") or ""), str(row.get("url_afiliado") or "")).get("severity") != "ok":
                    continue
                eligible_rows.append(dict(row))
                if len(eligible_rows) >= capped_limit:
                    break
            if len(eligible_rows) >= capped_limit:
                break
        rows = eligible_rows[:capped_limit]
    previews: list[dict[str, Any]] = []

    for row in rows:
        offer = dict(row)
        if _affiliate_audit(str(offer.get("loja") or ""), str(offer.get("url_afiliado") or "")).get("severity") != "ok":
            continue
        square_card_asset = generate_offer_square_card_asset(offer, suffix="social") if include_square_card_assets else None
        if include_story_assets:
            story_asset = generate_story_asset(offer)
            story_payload = {
                "image_url": story_asset["public_url"],
                "image_filename": story_asset["filename"],
                "caption": story_asset["caption"],
                "offer_url": story_asset["destination_url"],
            }
        else:
            story_payload = {
                "image_url": offer["imagem_url"],
                "image_filename": None,
                "caption": _story_caption_for_offer(offer),
                "offer_url": _destination_url(offer),
            }
        previews.append(
            {
                "offer_id": offer["id"],
                "slug": offer["slug"],
                "title": offer["titulo"],
                "store": _store_label(offer["loja"]),
                "category": _category_label(offer["categoria"]),
                "price": float(offer["preco"] or 0),
                "old_price": float(offer["preco_antigo"]) if offer.get("preco_antigo") else None,
                "discount_percent": int(offer["desconto_percentual"]) if offer.get("desconto_percentual") is not None else _offer_discount_percent(offer),
                "pix_price": float(offer["preco_pix"]) if offer.get("preco_pix") is not None else None,
                "other_price": float(offer["preco_outros_meios"]) if offer.get("preco_outros_meios") is not None else None,
                "installments": offer.get("parcelas_texto"),
                "shipping": offer.get("frete_texto"),
                "rating": float(offer["avaliacao_nota"]) if offer.get("avaliacao_nota") is not None else None,
                "rating_count": int(offer["avaliacao_total"]) if offer.get("avaliacao_total") is not None else None,
                "promotion_text": offer.get("promocao_texto"),
                "coupon": offer.get("cupom"),
                "image_url": offer["imagem_url"],
                "video_url": _offer_source_video_url(offer),
                "clicks": int(offer.get("clicks") or 0),
                "offer_url": _offer_url(offer["slug"]),
                "cta_url": _destination_url(offer),
                "headline": _headline_for_offer(offer),
                "caption": _caption_for_offer(offer),
                "facebook_payload": {
                    "message": _caption_for_offer(offer),
                    "link": _destination_url(offer),
                    "image_url": (square_card_asset["public_url"] if square_card_asset else offer["imagem_url"]),
                    "image_filename": (square_card_asset["filename"] if square_card_asset else None),
                },
                "instagram_payload": {
                    "image_url": (square_card_asset["public_url"] if square_card_asset else offer["imagem_url"]),
                    "image_filename": (square_card_asset["filename"] if square_card_asset else None),
                    "caption": _caption_for_offer(offer),
                },
                "story_payload": story_payload,
                "reel_payload": {
                    "caption": _story_caption_for_offer(offer),
                    "offer_url": _destination_url(offer),
                    "source_video_url": _offer_source_video_url(offer),
                },
            }
        )

    return previews


def publish_facebook_post(message: str, link: str | None = None) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        raise ValueError("A mensagem do post do Facebook nao pode ficar vazia.")

    payload = {"message": message, "access_token": _meta_page_token()}
    if link:
        payload["link"] = link.strip()

    with httpx.Client(timeout=20) as client:
        response = client.post(f"{_meta_api_base()}/{_meta_page_id()}/feed", data=payload)
        response.raise_for_status()
        data = response.json()

    return {"ok": True, "platform": "facebook", "page_id": _meta_page_id(), "result": data}


def publish_facebook_photo(image_url: str, caption: str) -> dict[str, Any]:
    image_url = (image_url or "").strip()
    caption = (caption or "").strip()
    if not image_url:
        raise ValueError("image_url da foto do Facebook nao pode ficar vazio.")
    if not caption:
        raise ValueError("caption da foto do Facebook nao pode ficar vazio.")

    payload = {
        "url": image_url,
        "caption": caption,
        "published": "true",
        "access_token": _meta_page_token(),
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(f"{_meta_api_base()}/{_meta_page_id()}/photos", data=payload)
        response.raise_for_status()
        data = response.json()

    return {"ok": True, "platform": "facebook_photo", "page_id": _meta_page_id(), "result": data}


def publish_facebook_story_photo(image_url: str) -> dict[str, Any]:
    image_url = (image_url or "").strip()
    if not image_url:
        raise ValueError("image_url do story do Facebook nao pode ficar vazio.")

    page_id = _meta_page_id()
    access_token = _meta_page_token()

    with httpx.Client(timeout=30) as client:
        upload_response = client.post(
            f"{_meta_api_base()}/{page_id}/photos",
            data={
                "url": image_url,
                "published": "false",
                "access_token": access_token,
            },
        )
        upload_response.raise_for_status()
        upload_data = upload_response.json()

        photo_id = str(upload_data.get("id") or "").strip()
        if not photo_id:
            raise ValueError(f"Resposta inesperada ao preparar foto do story do Facebook: {upload_data}")

        story_response = client.post(
            f"{_meta_api_base()}/{page_id}/photo_stories",
            data={
                "photo_id": photo_id,
                "access_token": access_token,
            },
        )
        story_response.raise_for_status()
        story_data = story_response.json()

    return {
        "ok": True,
        "platform": "facebook_story",
        "page_id": page_id,
        "photo_id": photo_id,
        "result": story_data,
    }


def publish_facebook_story_video(video_path: str) -> dict[str, Any]:
    normalized_path = Path(video_path)
    if not normalized_path.is_file():
        raise ValueError("Arquivo de video do story do Facebook nao encontrado.")

    page_id = _meta_page_id()
    access_token = _meta_page_token()
    file_size = normalized_path.stat().st_size
    if file_size <= 0:
        raise ValueError("Arquivo de video do story do Facebook vazio.")

    with httpx.Client(timeout=90) as client:
        start_response = client.post(
            f"{_meta_api_base()}/{page_id}/video_stories",
            data={
                "upload_phase": "start",
                "access_token": access_token,
            },
        )
        start_response.raise_for_status()
        start_data = start_response.json()

        video_id = (start_data.get("video_id") or "").strip()
        upload_url = (start_data.get("upload_url") or "").strip()
        if not video_id or not upload_url:
            raise ValueError(f"Resposta inesperada da Meta ao iniciar story em video: {start_data}")

        with normalized_path.open("rb") as video_file:
            upload_response = client.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                },
                content=video_file.read(),
            )
        upload_response.raise_for_status()

        finish_response = client.post(
            f"{_meta_api_base()}/{page_id}/video_stories",
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "access_token": access_token,
            },
        )
        finish_response.raise_for_status()
        finish_data = finish_response.json()

    return {
        "ok": True,
        "platform": "facebook_story_video",
        "page_id": page_id,
        "video_id": video_id,
        "result": finish_data,
    }


def publish_facebook_offer_batch(db, limit: int = 5, offer_ids: list[int] | None = None) -> dict[str, Any]:
    previews = build_meta_post_previews(
        db,
        limit=limit,
        offer_ids=offer_ids,
        include_story_assets=False,
        include_square_card_assets=True,
    )
    if not previews:
        raise ValueError("Nao ha ofertas elegiveis para publicar no Facebook.")

    published = []
    for item in previews:
        image_filename = (item.get("facebook_payload", {}).get("image_filename") or "").strip()
        if image_filename:
            deploy_stories_via_sftp(only_files=[image_filename])
        response = publish_facebook_photo(
            image_url=item["facebook_payload"]["image_url"],
            caption=item["facebook_payload"]["message"],
        )
        published.append(
            {
                "offer_id": item["offer_id"],
                "slug": item["slug"],
                "title": item["title"],
                "result": response["result"],
            }
        )

    return {"ok": True, "platform": "facebook", "page_id": _meta_page_id(), "count": len(published), "items": published}


def publish_facebook_reel(video_path: str, description: str) -> dict[str, Any]:
    normalized_path = Path(video_path)
    if not normalized_path.is_file():
        raise ValueError("Arquivo de reel nao encontrado para upload.")

    page_id = _meta_page_id()
    access_token = _meta_page_token()
    file_size = normalized_path.stat().st_size
    if file_size <= 0:
        raise ValueError("Arquivo de reel vazio.")

    with httpx.Client(timeout=90) as client:
        start_response = client.post(
            f"{_meta_api_base()}/{page_id}/video_reels",
            data={
                "upload_phase": "start",
                "access_token": access_token,
            },
        )
        start_response.raise_for_status()
        start_data = start_response.json()

        video_id = (start_data.get("video_id") or "").strip()
        upload_url = (start_data.get("upload_url") or "").strip()
        if not video_id or not upload_url:
            raise ValueError(f"Resposta inesperada da Meta ao iniciar reel: {start_data}")

        with normalized_path.open("rb") as video_file:
            upload_response = client.post(
                upload_url,
                headers={
                    "Authorization": f"OAuth {access_token}",
                    "offset": "0",
                    "file_size": str(file_size),
                },
                content=video_file.read(),
            )
        upload_response.raise_for_status()

        finish_response = client.post(
            f"{_meta_api_base()}/{page_id}/video_reels",
            data={
                "upload_phase": "finish",
                "video_id": video_id,
                "video_state": "PUBLISHED",
                "description": (description or "").strip(),
                "access_token": access_token,
            },
        )
        finish_response.raise_for_status()
        finish_data = finish_response.json()

    return {
        "ok": True,
        "platform": "facebook_reel",
        "page_id": page_id,
        "video_id": video_id,
        "result": finish_data,
    }


def create_instagram_media_container(image_url: str, caption: str) -> dict[str, Any]:
    image_url = (image_url or "").strip()
    caption = (caption or "").strip()
    if not image_url:
        raise ValueError("image_url do Instagram nao pode ficar vazio.")
    if not caption:
        raise ValueError("caption do Instagram nao pode ficar vazio.")

    payload = {"image_url": image_url, "caption": caption, "access_token": _meta_page_token()}

    with httpx.Client(timeout=20) as client:
        response = client.post(f"{_meta_api_base()}/{_meta_instagram_account_id()}/media", data=payload)
        response.raise_for_status()
        data = response.json()

    return {
        "ok": True,
        "platform": "instagram",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": data,
    }


def create_instagram_story_container(image_url: str | None = None, video_url: str | None = None) -> dict[str, Any]:
    image_url = (image_url or "").strip()
    video_url = (video_url or "").strip()
    if not image_url and not video_url:
        raise ValueError("image_url ou video_url do story nao pode ficar vazio.")

    payload = {
        "media_type": "STORIES",
        "access_token": _meta_page_token(),
    }
    if video_url:
        payload["video_url"] = video_url
    else:
        payload["image_url"] = image_url

    with httpx.Client(timeout=20) as client:
        response = client.post(f"{_meta_api_base()}/{_meta_instagram_account_id()}/media", data=payload)
        response.raise_for_status()
        data = response.json()

    return {
        "ok": True,
        "platform": "instagram_story",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": data,
    }


def create_instagram_reel_container(video_url: str, caption: str, *, share_to_feed: bool = True) -> dict[str, Any]:
    video_url = (video_url or "").strip()
    caption = (caption or "").strip()
    if not video_url:
        raise ValueError("video_url do reel do Instagram nao pode ficar vazio.")
    if not caption:
        raise ValueError("caption do reel do Instagram nao pode ficar vazio.")

    payload = {
        "video_url": video_url,
        "media_type": "REELS",
        "caption": caption,
        "share_to_feed": "true" if share_to_feed else "false",
        "access_token": _meta_page_token(),
    }

    with httpx.Client(timeout=30) as client:
        response = client.post(f"{_meta_api_base()}/{_meta_instagram_account_id()}/media", data=payload)
        response.raise_for_status()
        data = response.json()

    return {
        "ok": True,
        "platform": "instagram_reel",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": data,
    }


def get_instagram_container_status(creation_id: str) -> dict[str, Any]:
    creation_id = (creation_id or "").strip()
    if not creation_id:
        raise ValueError("creation_id do Instagram nao pode ficar vazio.")

    params = {
        "fields": "status_code,status,status_message",
        "access_token": _meta_page_token(),
    }

    with httpx.Client(timeout=20) as client:
        response = client.get(f"{_meta_api_base()}/{creation_id}", params=params)
        response.raise_for_status()
        data = response.json()

    return {
        "ok": True,
        "platform": "instagram_container_status",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": data,
    }


def get_instagram_content_publishing_limit() -> dict[str, Any]:
    params = {
        "fields": "quota_usage,config",
        "access_token": _meta_page_token(),
    }

    with httpx.Client(timeout=20) as client:
        response = client.get(f"{_meta_api_base()}/{_meta_instagram_account_id()}/content_publishing_limit", params=params)
        response.raise_for_status()
        data = response.json()

    bucket = ((data.get("data") or [{}])[0]) if isinstance(data, dict) else {}
    config = bucket.get("config") or {}
    quota_total = int(config.get("quota_total") or 0)
    quota_usage = int(bucket.get("quota_usage") or 0)
    quota_duration = int(config.get("quota_duration") or 0)
    remaining = max(0, quota_total - quota_usage) if quota_total > 0 else 0

    return {
        "ok": True,
        "platform": "instagram_content_publishing_limit",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": {
            "quota_total": quota_total,
            "quota_usage": quota_usage,
            "quota_remaining": remaining,
            "quota_duration_seconds": quota_duration,
        },
    }


def wait_for_instagram_container_ready(creation_id: str, *, timeout_seconds: int = 120, poll_interval_seconds: int = 5) -> dict[str, Any]:
    deadline = time.time() + max(10, timeout_seconds)
    last_status: dict[str, Any] | None = None

    while time.time() <= deadline:
        try:
            status_payload = get_instagram_container_status(creation_id)
        except httpx.HTTPStatusError as exc:
            if exc.response is not None and exc.response.status_code == 400:
                return {
                    "ok": True,
                    "platform": "instagram_container_status",
                    "instagram_business_account_id": _meta_instagram_account_id(),
                    "result": {"status_code": "UNAVAILABLE"},
                }
            raise
        status_data = status_payload.get("result") or {}
        last_status = status_data
        status_code = str(status_data.get("status_code") or status_data.get("status") or "").strip().upper()

        if status_code in {"FINISHED", "PUBLISHED"}:
            return status_payload
        if status_code in {"ERROR", "EXPIRED", "FAILED"}:
            raise ValueError(f"Instagram retornou status invalido para o container: {status_data}")

        time.sleep(max(1, poll_interval_seconds))

    raise ValueError(f"Container do Instagram nao ficou pronto a tempo: {last_status or {}}")


def publish_instagram_container(creation_id: str) -> dict[str, Any]:
    creation_id = (creation_id or "").strip()
    if not creation_id:
        raise ValueError("creation_id do Instagram nao pode ficar vazio.")

    wait_for_instagram_container_ready(creation_id)
    payload = {"creation_id": creation_id, "access_token": _meta_page_token()}
    last_exc: httpx.HTTPStatusError | None = None

    with httpx.Client(timeout=20) as client:
        for attempt in range(12):
            try:
                response = client.post(f"{_meta_api_base()}/{_meta_instagram_account_id()}/media_publish", data=payload)
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response is None or exc.response.status_code != 400 or attempt >= 11:
                    raise
                time.sleep(5)
        else:
            if last_exc is not None:
                raise last_exc
            raise ValueError("Falha ao publicar container do Instagram.")

    return {
        "ok": True,
        "platform": "instagram",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": data,
    }
