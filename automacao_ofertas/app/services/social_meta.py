import html
import os
import re
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from sqlalchemy import bindparam, text

from app.services.sftp_deploy import ensure_stories_dir, story_public_url


SELECT_TOP_OFFERS_SQL = text(
    """
    SELECT
      o.id,
      o.slug,
      o.titulo,
      o.descricao,
      o.preco,
      o.preco_antigo,
      o.loja,
      o.url_afiliado,
      o.cupom,
      o.imagem_url,
      o.categoria,
      o.tags,
      o.destaque,
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
        :search_query = ''
        OR o.titulo LIKE :search_like
        OR o.slug LIKE :search_like
        OR o.loja LIKE :search_like
        OR o.categoria LIKE :search_like
      )
    GROUP BY o.id, o.slug, o.titulo, o.descricao, o.preco, o.preco_antigo, o.loja, o.url_afiliado, o.cupom, o.imagem_url, o.categoria, o.tags, o.destaque, o.atualizado_em
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC, o.preco ASC
    LIMIT :limit
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
      o.loja,
      o.url_afiliado,
      o.cupom,
      o.imagem_url,
      o.categoria,
      o.tags,
      o.destaque,
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
    GROUP BY o.id, o.slug, o.titulo, o.descricao, o.preco, o.preco_antigo, o.loja, o.url_afiliado, o.cupom, o.imagem_url, o.categoria, o.tags, o.destaque, o.atualizado_em
    ORDER BY clicks DESC, o.destaque DESC, o.atualizado_em DESC, o.preco ASC
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
        if has_social or has_matt or (has_wid and has_recos and has_affiliate_profile):
            return {"severity": "ok", "reason": "Link oficial Mercado Livre."}
        if has_wid and (has_sid or has_polycard or has_affiliate_profile):
            return {"severity": "suspect", "reason": "Link ML com wid, mas sem garantia de origem oficial."}
        return {"severity": "broken", "reason": "Link ML sem marcador oficial."}

    if store_value == "shopee":
        if "an_" in value or "mmp_pid=" in value or "utm_medium=affiliates" in value:
            return {"severity": "ok", "reason": "Link Shopee com marcador afiliado visivel."}
        if "s.shopee.com.br/" in value:
            return {"severity": "suspect", "reason": "Shortlink Shopee sem marcador visivel."}
        return {"severity": "broken", "reason": "Link Shopee sem marcador afiliado visivel."}

    if store_value == "amazon":
        if "tag=" in value:
            return {"severity": "ok", "reason": "Link Amazon com tag."}
        return {"severity": "broken", "reason": "Link Amazon sem tag."}

    return {"severity": "suspect", "reason": "Loja sem regra de afiliado definida."}


def _site_base_url() -> str:
    return os.getenv("SITE_BASE_URL", "https://zeropreco.com.br").rstrip("/")


def _meta_api_base() -> str:
    version = (os.getenv("META_GRAPH_API_VERSION") or "v23.0").strip() or "v23.0"
    return f"https://graph.facebook.com/{version}"


def _meta_token() -> str:
    token = (os.getenv("META_ACCESS_TOKEN") or "").strip()
    if not token:
        raise ValueError("META_ACCESS_TOKEN nao preenchido no .env.")
    return token


def _meta_page_id() -> str:
    page_id = (os.getenv("META_PAGE_ID") or "").strip()
    if not page_id:
        raise ValueError("META_PAGE_ID nao preenchido no .env.")
    return page_id


def _meta_page_token() -> str:
    user_token = _meta_token()
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


def _offer_url(slug: str) -> str:
    return f"{_site_base_url()}/oferta.php?slug={slug}"


def _cta_url(slug: str) -> str:
    return f"{_site_base_url()}/oferta.php?slug={slug}&go=1"


def _destination_url(offer: dict[str, Any]) -> str:
    preferred = (offer.get("url_afiliado") or "").strip()
    if preferred:
        return preferred
    return _cta_url(offer["slug"])


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
    category = _category_label(offer["categoria"])
    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))
    coupon = (offer.get("cupom") or "").strip()
    destination_url = _destination_url(offer)
    has_direct_store_link = bool((offer.get("url_afiliado") or "").strip())

    lead = f"{offer['titulo']}\n{price} na {store}"
    details = [f"Categoria: {category}"]
    if discount > 0:
        details.append(f"Desconto aproximado: {discount}%")
    if coupon:
        details.append(f"Cupom: {coupon}")

    lines = [
        lead,
        " | ".join(details),
        "Abrir direto na loja:" if has_direct_store_link else "Veja o produto no site:",
        destination_url,
        "",
        "#ofertas #promocao #zeropreco",
    ]
    return "\n".join(lines)


def _story_caption_for_offer(offer: dict[str, Any]) -> str:
    store = _store_label(offer["loja"])
    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))
    coupon = (offer.get("cupom") or "").strip()
    destination_url = _destination_url(offer)
    has_direct_store_link = bool((offer.get("url_afiliado") or "").strip())
    parts = [f"{offer['titulo']}", f"{_money(offer['preco'])} na {store}"]
    if discount > 0:
        parts.append(f"Aprox. {discount}% OFF")
    if coupon:
        parts.append(f"Cupom: {coupon}")
    parts.append("Abrir direto na loja:" if has_direct_store_link else "Ver produto no site:")
    parts.append(destination_url)
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
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
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


def generate_story_asset(offer: dict[str, Any]) -> dict[str, Any]:
    filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}.jpg"
    destination = ensure_stories_dir() / filename
    destination_url = _destination_url(offer)
    destination_host = _display_url(destination_url)
    has_direct_store_link = bool((offer.get("url_afiliado") or "").strip())
    destination_label = "Abrir na loja" if has_direct_store_link else "Ver no site"
    destination_label_secondary = "Link direto deste produto" if has_direct_store_link else "Pagina do produto no Zero Preco"

    image = Image.new("RGB", (1080, 1920), "#0a2a67")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1080, 1920), fill="#0a2a67")
    draw.ellipse((700, 80, 1050, 430), fill="#1b4fc3")
    draw.ellipse((-120, 1450, 260, 1830), fill="#12398f")
    draw.rounded_rectangle((54, 54, 1026, 1866), radius=42, outline="#2f65db", width=4)

    title_font = _load_font(58, bold=True)
    price_font = _load_font(96, bold=True)
    label_font = _load_font(30, bold=True)
    text_font = _load_font(32)
    cta_font = _load_font(34, bold=True)
    cta_small_font = _load_font(26, bold=True)
    micro_font = _load_font(22)
    domain_font = _load_font(40, bold=True)

    draw.text((80, 120), "ZERO PRECO", font=label_font, fill="#dbe7ff")

    title_lines = _wrap_text(offer["titulo"], 24)[:3]
    y = 250
    for line in title_lines:
        draw.text((80, y), line, font=title_font, fill="#f4f7fb")
        y += 68

    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))
    if discount > 0:
        draw.rounded_rectangle((80, 190, 310, 260), radius=24, fill="#143b90")
        draw.text((116, 208), f"{discount}% OFF", font=label_font, fill="#f4f7fb")

    draw.text((80, y + 52), _money(offer["preco"]), font=price_font, fill="#ffffff")
    if offer.get("preco_antigo"):
        draw.text((80, y + 162), f"De {_money(offer['preco_antigo'])}", font=text_font, fill="#b9c8e6")

    draw.text(
        (80, y + 226),
        f"{_store_label(offer['loja'])} | {_category_label(offer['categoria'])}",
        font=text_font,
        fill="#dbe7ff",
    )

    product_card_box = (80, 760, 1000, 1310)
    draw.rounded_rectangle(product_card_box, radius=36, fill="#f8fbff")
    product_image = _fit_remote_product_image(offer.get("imagem_url"), (840, 470))
    if product_image is not None:
        image.paste(product_image, (120, 800))
        draw.rounded_rectangle((120, 800, 960, 1270), radius=28, outline="#d7e4ff", width=4)
    else:
        draw.rounded_rectangle((120, 800, 960, 1270), radius=28, fill="#d9e5ff")
        draw.text((180, 1015), "Imagem do produto", font=cta_font, fill="#0b2d78")

    draw.rounded_rectangle((80, 1360, 760, 1496), radius=28, fill="#ffffff")
    draw.text((120, 1392), destination_label, font=cta_font, fill="#0b2d78")
    draw.text((120, 1438), destination_label_secondary, font=cta_small_font, fill="#0b2d78")

    draw.text((80, 1560), destination_host, font=domain_font, fill="#ffffff")
    draw.text(
        (80, 1616),
        "Siga para a loja parceira." if has_direct_store_link else "Abra a pagina do produto no site.",
        font=text_font,
        fill="#dbe7ff",
    )
    draw.text((80, 1660), "Use o link publicado junto da oferta.", font=micro_font, fill="#dbe7ff")

    coupon_text = (offer.get("cupom") or "").strip()
    if coupon_text:
        draw.rounded_rectangle((80, 650, 500, 730), radius=20, fill="#113885")
        draw.text((110, 676), f"Cupom: {coupon_text[:18]}", font=label_font, fill="#f4f7fb")

    image.save(destination, format="JPEG", quality=92, optimize=True)
    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": story_public_url(filename),
        "caption": _story_caption_for_offer(offer),
        "destination_url": destination_url,
    }


def generate_reel_asset(offer: dict[str, Any], *, duration_seconds: int = 6, fps: int = 24) -> dict[str, Any]:
    story_asset = generate_story_asset(offer)
    source_path = Path(story_asset["file_path"])
    if not source_path.is_file():
        raise ValueError("Arte base do reel nao foi gerada.")

    filename = source_path.stem + "-reel.mp4"
    destination = source_path.with_name(filename)
    total_frames = max(1, duration_seconds * fps)

    with Image.open(source_path) as source_image:
        base_image = source_image.convert("RGB")
        width, height = base_image.size
        writer = imageio.get_writer(
            str(destination),
            fps=fps,
            codec="libx264",
            pixelformat="yuv420p",
            macro_block_size=None,
        )
        try:
            for frame_index in range(total_frames):
                progress = frame_index / max(total_frames - 1, 1)
                zoom = 1.0 + (0.035 * progress)
                resized = base_image.resize((int(width * zoom), int(height * zoom)), Image.Resampling.LANCZOS)
                frame = ImageOps.fit(resized, (width, height), method=Image.Resampling.LANCZOS, centering=(0.5, 0.4))
                writer.append_data(np.asarray(frame))
        finally:
            writer.close()

    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": story_public_url(filename),
        "caption": _story_caption_for_offer(offer),
        "destination_url": story_asset["destination_url"],
        "poster_url": story_asset["public_url"],
    }


def build_meta_post_previews(
    db,
    limit: int = 12,
    offer_ids: list[int] | None = None,
    include_story_assets: bool = True,
    search_query: str | None = None,
) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 200))
    fetch_limit = max(capped_limit, len(offer_ids or []), 160)
    normalized_query = (search_query or "").strip()
    if offer_ids:
        rows = db.execute(
            SELECT_OFFERS_BY_IDS_SQL,
            {"offer_ids": [int(offer_id) for offer_id in offer_ids]},
        ).mappings().all()
        selected_map = {int(row["id"]): row for row in rows}
        rows = [dict(selected_map[offer_id]) for offer_id in offer_ids if int(offer_id) in selected_map][:capped_limit]
    else:
        params = {
            "limit": fetch_limit,
            "search_query": normalized_query,
            "search_like": f"%{normalized_query}%",
        }
        rows = db.execute(SELECT_TOP_OFFERS_SQL, params).mappings().all()
        eligible_rows = [
            dict(row)
            for row in rows
            if _affiliate_audit(str(row.get("loja") or ""), str(row.get("url_afiliado") or "")).get("severity") == "ok"
        ]
        if normalized_query:
            rows = eligible_rows[:capped_limit]
        else:
            rows = _diversify_offer_rows(eligible_rows, capped_limit)
    previews: list[dict[str, Any]] = []

    for row in rows:
        offer = dict(row)
        if _affiliate_audit(str(offer.get("loja") or ""), str(offer.get("url_afiliado") or "")).get("severity") != "ok":
            continue
        if include_story_assets:
            story_asset = generate_story_asset(offer)
            story_payload = {
                "image_url": story_asset["public_url"],
                "caption": story_asset["caption"],
                "offer_url": story_asset["destination_url"],
            }
        else:
            story_payload = {
                "image_url": offer["imagem_url"],
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
                "coupon": offer.get("cupom"),
                "image_url": offer["imagem_url"],
                "clicks": int(offer.get("clicks") or 0),
                "offer_url": _offer_url(offer["slug"]),
                "cta_url": _destination_url(offer),
                "headline": _headline_for_offer(offer),
                "caption": _caption_for_offer(offer),
                "facebook_payload": {
                    "message": _caption_for_offer(offer),
                    "link": _destination_url(offer),
                },
                "instagram_payload": {
                    "image_url": offer["imagem_url"],
                    "caption": _caption_for_offer(offer),
                },
                "story_payload": story_payload,
                "reel_payload": {
                    "caption": _story_caption_for_offer(offer),
                    "offer_url": _destination_url(offer),
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


def publish_facebook_offer_batch(db, limit: int = 5, offer_ids: list[int] | None = None) -> dict[str, Any]:
    previews = build_meta_post_previews(db, limit=limit, offer_ids=offer_ids, include_story_assets=False)
    if not previews:
        raise ValueError("Nao ha ofertas elegiveis para publicar no Facebook.")

    published = []
    for item in previews:
        response = publish_facebook_post(
            message=item["facebook_payload"]["message"],
            link=item["facebook_payload"]["link"],
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

    payload = {"image_url": image_url, "caption": caption, "access_token": _meta_token()}

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


def create_instagram_story_container(image_url: str) -> dict[str, Any]:
    image_url = (image_url or "").strip()
    if not image_url:
        raise ValueError("image_url do story nao pode ficar vazio.")

    payload = {
        "image_url": image_url,
        "media_type": "STORIES",
        "access_token": _meta_token(),
    }

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


def publish_instagram_container(creation_id: str) -> dict[str, Any]:
    creation_id = (creation_id or "").strip()
    if not creation_id:
        raise ValueError("creation_id do Instagram nao pode ficar vazio.")

    payload = {"creation_id": creation_id, "access_token": _meta_token()}

    with httpx.Client(timeout=20) as client:
        response = client.post(f"{_meta_api_base()}/{_meta_instagram_account_id()}/media_publish", data=payload)
        response.raise_for_status()
        data = response.json()

    return {
        "ok": True,
        "platform": "instagram",
        "instagram_business_account_id": _meta_instagram_account_id(),
        "result": data,
    }
