import html
import os
import re
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import text


SELECT_TOP_OFFERS_SQL = text(
    """
    SELECT
      id,
      slug,
      titulo,
      descricao,
      preco,
      preco_antigo,
      loja,
      cupom,
      imagem_url,
      categoria,
      tags,
      destaque,
      atualizado_em
    FROM ofertas
    WHERE ativo = 1
      AND (expira_em IS NULL OR expira_em > NOW())
      AND imagem_url IS NOT NULL
      AND imagem_url <> ''
    ORDER BY destaque DESC, atualizado_em DESC, preco ASC
    LIMIT :limit
    """
)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


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


def _generated_story_dir() -> Path:
    directory = _project_root() / "public_html" / "generated" / "meta-stories"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _story_public_url(filename: str) -> str:
    return f"{_site_base_url()}/generated/meta-stories/{filename}"


def _store_label(value: str) -> str:
    lowered = (value or "").strip().lower()
    mapping = {
        "mercado livre": "Mercado Livre",
        "shopee": "Shopee",
        "amazon": "Amazon",
        "tiktok": "TikTok Shop",
    }
    return mapping.get(lowered, (value or "Loja").strip() or "Loja")


def _category_label(value: str) -> str:
    raw = (value or "").strip()
    if not raw or raw.lower() == "geral":
        return "ofertas"
    return raw.replace("-", " ").replace("_", " ")


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


def _headline_for_offer(offer: dict[str, Any]) -> str:
    return f"{offer['titulo']} por {_money(offer['preco'])}"


def _caption_for_offer(offer: dict[str, Any]) -> str:
    price = _money(offer["preco"])
    store = _store_label(offer["loja"])
    category = _category_label(offer["categoria"])
    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))
    coupon = (offer.get("cupom") or "").strip()

    lead = f"{offer['titulo']}\n{price} na {store}"
    details = [f"Categoria: {category}"]
    if discount > 0:
        details.append(f"Desconto aproximado: {discount}%")
    if coupon:
        details.append(f"Cupom: {coupon}")

    lines = [
        lead,
        " | ".join(details),
        "Veja a oferta completa no Zero Preco.",
        _offer_url(offer["slug"]),
        "",
        "#ofertas #promocao #zeropreco",
    ]
    return "\n".join(lines)


def _story_caption_for_offer(offer: dict[str, Any]) -> str:
    store = _store_label(offer["loja"])
    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))
    parts = [f"{offer['titulo']}", f"{_money(offer['preco'])} na {store}"]
    if discount > 0:
        parts.append(f"Aprox. {discount}% OFF")
    parts.append("Link no perfil e no Zero Preco.")
    return "\n".join(parts)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()
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


def generate_story_asset(offer: dict[str, Any]) -> dict[str, Any]:
    filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}.jpg"
    destination = _generated_story_dir() / filename

    image = Image.new("RGB", (1080, 1920), "#0a2a67")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1080, 1920), fill="#0a2a67")
    draw.ellipse((700, 80, 1050, 430), fill="#1b4fc3")
    draw.ellipse((-120, 1450, 260, 1830), fill="#12398f")
    draw.rounded_rectangle((54, 54, 1026, 1866), radius=42, outline="#2f65db", width=4)

    title_font = _load_font(60, bold=True)
    price_font = _load_font(96, bold=True)
    label_font = _load_font(30, bold=True)
    text_font = _load_font(34)
    cta_font = _load_font(40, bold=True)

    draw.text((80, 120), "ZERO PRECO", font=label_font, fill="#dbe7ff")

    title_lines = _wrap_text(offer["titulo"], 24)[:4]
    y = 260
    for line in title_lines:
        draw.text((80, y), line, font=title_font, fill="#f4f7fb")
        y += 72

    discount = _discount_percent(offer["preco"], offer.get("preco_antigo"))
    if discount > 0:
        draw.rounded_rectangle((80, 190, 310, 260), radius=24, fill="#143b90")
        draw.text((116, 208), f"{discount}% OFF", font=label_font, fill="#f4f7fb")

    draw.text((80, y + 70), _money(offer["preco"]), font=price_font, fill="#ffffff")
    if offer.get("preco_antigo"):
        draw.text((80, y + 180), f"De {_money(offer['preco_antigo'])}", font=text_font, fill="#b9c8e6")

    draw.text(
        (80, y + 250),
        f"{_store_label(offer['loja'])} | {_category_label(offer['categoria'])}",
        font=text_font,
        fill="#dbe7ff",
    )

    draw.rounded_rectangle((80, 1100, 600, 1210), radius=28, fill="#ffffff")
    draw.text((140, 1140), "Ver oferta no site", font=cta_font, fill="#0b2d78")

    draw.text((80, 1320), "zeropreco.com.br", font=text_font, fill="#dbe7ff")
    draw.text((80, 1370), _offer_url(offer["slug"]), font=_load_font(20), fill="#dbe7ff")

    coupon_text = (offer.get("cupom") or "").strip()
    if coupon_text:
        draw.rounded_rectangle((80, 980, 500, 1060), radius=20, fill="#113885")
        draw.text((110, 1006), f"Cupom: {coupon_text[:18]}", font=label_font, fill="#f4f7fb")

    image.save(destination, format="JPEG", quality=92, optimize=True)
    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": _story_public_url(filename),
        "caption": _story_caption_for_offer(offer),
    }


def build_meta_post_previews(db, limit: int = 12) -> list[dict[str, Any]]:
    rows = db.execute(SELECT_TOP_OFFERS_SQL, {"limit": max(1, min(limit, 50))}).mappings().all()
    previews: list[dict[str, Any]] = []

    for row in rows:
        offer = dict(row)
        story_asset = generate_story_asset(offer)
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
                "offer_url": _offer_url(offer["slug"]),
                "cta_url": _cta_url(offer["slug"]),
                "headline": _headline_for_offer(offer),
                "caption": _caption_for_offer(offer),
                "facebook_payload": {
                    "message": _caption_for_offer(offer),
                    "link": _offer_url(offer["slug"]),
                },
                "instagram_payload": {
                    "image_url": offer["imagem_url"],
                    "caption": _caption_for_offer(offer),
                },
                "story_payload": {
                    "image_url": story_asset["public_url"],
                    "caption": story_asset["caption"],
                    "offer_url": _offer_url(offer["slug"]),
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


def publish_facebook_offer_batch(db, limit: int = 5) -> dict[str, Any]:
    previews = build_meta_post_previews(db, limit=limit)
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
