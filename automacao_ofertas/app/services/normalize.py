import os
from urllib.parse import parse_qsl, quote_plus, urlencode, urlparse, urlunparse

from app.schemas import NormalizedOffer


def repair_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    suspicious = ("Ã", "Â", "â€™", "â€œ", "â€", "�")
    if any(token in text for token in suspicious):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return text


def build_slug(title: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in title)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:170] or "item"


def ensure_affiliate_link(url: str, store: str, tag: str | None = None, item_id: str | None = None, product_id: str | None = None) -> str:
    if not tag:
        return url

    normalized_store = store.strip().lower()

    if normalized_store == "mercado livre":
        template = os.getenv("MERCADOLIVRE_AFFILIATE_URL_TEMPLATE", "").strip()
        if template:
            return (
                template
                .replace("{url}", url)
                .replace("{encoded_url}", quote_plus(url))
                .replace("{tag}", tag)
                .replace("{item_id}", item_id or "")
                .replace("{product_id}", product_id or "")
            )

        if item_id:
            parsed = urlparse(url)
            query = parsed.query
            query_sep = "&" if query else ""
            query = f"{query}{query_sep}pdp_filters=item_id%3A{item_id}"
            fragment = f"polycard_client=affiliates&wid={item_id}&sid=affiliates"
            return urlunparse(parsed._replace(query=query, fragment=fragment))

        return url

    if normalized_store == "amazon":
        parsed = urlparse(url)
        query_items = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "tag"]
        query_items.append(("tag", tag))
        return urlunparse(parsed._replace(query=urlencode(query_items), fragment=""))

    sep = "&" if "?" in url else "?"
    return f"{url}{sep}aff={tag}"


def ensure_tags(tags: str | None, store: str, affiliate_tag: str | None) -> str | None:
    base_tags = [repair_text(tag) for tag in (tags or "").split(",") if repair_text(tag)]

    if store.strip().lower() == "mercado livre" and affiliate_tag:
        marker = f"meli_grant:{affiliate_tag}"
        if marker not in base_tags:
            base_tags.append(marker)

    return ",".join(base_tags) or None


def normalize_offer(raw: dict, store: str, affiliate_tag: str | None = None) -> NormalizedOffer:
    clean_store = repair_text(store)
    clean_url = repair_text(raw.get("url", "#"))

    return NormalizedOffer(
        titulo=repair_text(raw.get("title", "Oferta sem titulo")),
        descricao=repair_text(raw.get("description", "")),
        preco=float(raw.get("price", 0)),
        preco_antigo=float(raw["old_price"]) if raw.get("old_price") else None,
        loja=clean_store,
        url_afiliado=ensure_affiliate_link(
            clean_url,
            clean_store,
            affiliate_tag,
            raw.get("item_id"),
            raw.get("product_id"),
        ),
        cupom=repair_text(raw.get("coupon")) or None,
        imagem_url=repair_text(raw.get("image")) or None,
        categoria=repair_text(raw.get("category", "ofertas")),
        tags=ensure_tags(raw.get("tags"), clean_store, affiliate_tag),
        destaque=int(raw.get("featured", 0)),
        ativo=1,
    )
