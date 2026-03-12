import os
import re
from urllib.parse import parse_qs, unquote, urlparse

from sqlalchemy import text

from app.services.normalize import _extract_meli_item_id, _has_meli_affiliate_marker, ensure_affiliate_link
from app.services.normalize import build_slug


SELECT_AMAZON_OFFERS_SQL = text(
    """
    SELECT id, titulo, url_afiliado, ativo
    FROM ofertas
    WHERE LOWER(loja) = LOWER(:store)
      AND (:only_inactive = 0 OR ativo = 0)
    ORDER BY id DESC
    """
)

UPDATE_OFFER_SQL = text(
    """
    UPDATE ofertas
    SET url_afiliado = :url_afiliado,
        ativo = :ativo
    WHERE id = :id
    """
)

SELECT_STORE_OFFERS_SQL = text(
    """
    SELECT id, slug, titulo, url_afiliado, ativo
    FROM ofertas
    WHERE LOWER(loja) = LOWER(:store)
    ORDER BY id DESC
    """
)


def _has_exact_amazon_tag(url: str, affiliate_tag: str) -> bool:
    parsed = urlparse((url or "").strip())
    values = parse_qs(parsed.query, keep_blank_values=True)
    return ((values.get("tag") or [None])[0] or "").strip() == affiliate_tag


def repair_amazon_affiliate_links(db, only_inactive: bool = True) -> dict[str, int | str]:
    affiliate_tag = (os.getenv("AMAZON_AFFILIATE_TAG") or "").strip()
    if not affiliate_tag:
        raise ValueError("AMAZON_AFFILIATE_TAG nao configurada no .env.")

    rows = db.execute(
        SELECT_AMAZON_OFFERS_SQL,
        {"store": "Amazon", "only_inactive": 1 if only_inactive else 0},
    ).mappings().all()

    summary = {
        "processed": 0,
        "updated": 0,
        "reactivated": 0,
        "skipped": 0,
        "invalid": 0,
        "tag": affiliate_tag,
    }

    for row in rows:
        summary["processed"] += 1
        current_url = str(row.get("url_afiliado") or "").strip()
        if not current_url:
            summary["invalid"] += 1
            continue

        fixed_url = ensure_affiliate_link(current_url, "Amazon", affiliate_tag)
        if not _has_exact_amazon_tag(fixed_url, affiliate_tag):
            summary["invalid"] += 1
            continue

        next_active = 1
        changed = fixed_url != current_url or int(row.get("ativo") or 0) != next_active
        if not changed:
            summary["skipped"] += 1
            continue

        db.execute(
            UPDATE_OFFER_SQL,
            {"id": row["id"], "url_afiliado": fixed_url, "ativo": next_active},
        )
        summary["updated"] += 1
        if int(row.get("ativo") or 0) != 1:
            summary["reactivated"] += 1

    return summary


def repair_mercadolivre_affiliate_links(db, only_inactive: bool = True) -> dict[str, int | str]:
    affiliate_tag = (os.getenv("MERCADOLIVRE_AFFILIATE_TAG") or "").strip()
    template = (os.getenv("MERCADOLIVRE_AFFILIATE_URL_TEMPLATE") or "").strip()
    if not affiliate_tag and not template:
        raise ValueError(
            "Configure ao menos MERCADOLIVRE_AFFILIATE_URL_TEMPLATE ou mantenha links oficiais ja gerados na base."
        )

    rows = db.execute(
        SELECT_AMAZON_OFFERS_SQL,
        {"store": "Mercado Livre", "only_inactive": 1 if only_inactive else 0},
    ).mappings().all()

    summary = {
        "processed": 0,
        "updated": 0,
        "reactivated": 0,
        "skipped": 0,
        "invalid": 0,
        "tag": affiliate_tag,
        "template_configured": bool(template),
    }

    for row in rows:
        summary["processed"] += 1
        current_url = str(row.get("url_afiliado") or "").strip()
        if not current_url:
            summary["invalid"] += 1
            continue

        item_id = _extract_meli_item_id(current_url)
        product_id = None
        path = urlparse(current_url).path or ""
        parts = [part for part in path.split("/") if part]
        for part in parts:
            upper = part.upper()
            if upper.startswith("MLB") and len(upper) > 3:
                product_id = upper
                break

        fixed_url = current_url
        if not _has_meli_affiliate_marker(current_url) and template:
            fixed_url = ensure_affiliate_link(current_url, "Mercado Livre", affiliate_tag, item_id, product_id)

        if not _has_meli_affiliate_marker(fixed_url):
            summary["invalid"] += 1
            continue

        next_active = 1
        changed = fixed_url != current_url or int(row.get("ativo") or 0) != next_active
        if not changed:
            summary["skipped"] += 1
            continue

        db.execute(
            UPDATE_OFFER_SQL,
            {"id": row["id"], "url_afiliado": fixed_url, "ativo": next_active},
        )
        summary["updated"] += 1
        if int(row.get("ativo") or 0) != 1:
            summary["reactivated"] += 1

    return summary


def _has_shopee_affiliate_marker(url: str) -> bool:
    value = (url or "").strip().lower()
    return (
        "mmp_pid=" in value
        or "utm_medium=affiliates" in value
        or "an_" in value
        or "s.shopee.com.br/" in value
    )


def repair_shopee_affiliate_links(db, only_inactive: bool = True) -> dict[str, int | str]:
    rows = db.execute(
        SELECT_AMAZON_OFFERS_SQL,
        {"store": "Shopee", "only_inactive": 1 if only_inactive else 0},
    ).mappings().all()

    summary = {
        "processed": 0,
        "updated": 0,
        "reactivated": 0,
        "skipped": 0,
        "invalid": 0,
    }

    for row in rows:
        summary["processed"] += 1
        current_url = str(row.get("url_afiliado") or "").strip()
        if not current_url:
            summary["invalid"] += 1
            continue

        if not _has_shopee_affiliate_marker(current_url):
            summary["invalid"] += 1
            continue

        next_active = 1
        if int(row.get("ativo") or 0) == next_active:
            summary["skipped"] += 1
            continue

        db.execute(
            UPDATE_OFFER_SQL,
            {"id": row["id"], "url_afiliado": current_url, "ativo": next_active},
        )
        summary["updated"] += 1
        summary["reactivated"] += 1

    return summary


def _extract_ml_product_id(url: str) -> str | None:
    match = re.search(r"/p/(MLB\d+)", (url or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _normalize_input_links(links: list[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in links or []:
        value = str(raw or "").strip()
        if not value:
            continue
        if not value.startswith(("http://", "https://")):
            value = f"https://{value.lstrip('/')}"
        if value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    if not cleaned:
        raise ValueError("Cole pelo menos um link oficial do Mercado Livre.")
    return cleaned


def _extract_title_from_ml_url(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    segments = [segment for segment in path.split("/") if segment]
    for segment in reversed(segments):
        upper = segment.upper()
        if upper.startswith("MLB") or segment == "p":
            continue
        text = re.sub(r"[-_]+", " ", segment).strip()
        if text:
            return text[:180]
    return "Oferta Mercado Livre"


def _load_store_offer_indexes(db, store: str) -> tuple[dict[str, dict], dict[str, dict]]:
    rows = db.execute(SELECT_STORE_OFFERS_SQL, {"store": store}).mappings().all()
    by_product_id: dict[str, dict] = {}
    by_slug: dict[str, dict] = {}
    for row in rows:
        offer = dict(row)
        product_id = _extract_ml_product_id(str(offer.get("url_afiliado") or ""))
        if product_id and product_id not in by_product_id:
            by_product_id[product_id] = offer
        slug = str(offer.get("slug") or "").strip()
        if slug and slug not in by_slug:
            by_slug[slug] = offer
    return by_product_id, by_slug


def preview_mercadolivre_existing_offer_relinks(db, links: list[str]) -> list[dict]:
    by_product_id, by_slug = _load_store_offer_indexes(db, "Mercado Livre")

    results: list[dict] = []
    for link in _normalize_input_links(links):
        host = (urlparse(link).netloc or "").lower()
        if "mercadolivre" not in host and "mercadolibre" not in host:
            results.append(
                {
                    "provider": "unknown",
                    "store": "Marketplace",
                    "url": link,
                    "canonical_url": link,
                    "selected": False,
                    "affiliate_detected": False,
                    "match_found": False,
                    "match_reason": "Link nao pertence ao Mercado Livre.",
                }
            )
            continue

        canonical_url = link
        title = _extract_title_from_ml_url(link)
        product_id = _extract_ml_product_id(canonical_url) or _extract_meli_item_id(link)
        matched = by_product_id.get(product_id or "")
        reason = "Produto encontrado por MLB."

        if not matched:
            slug = build_slug(title)
            matched = by_slug.get(slug)
            reason = "Produto encontrado por slug do titulo."

        if not matched:
            results.append(
                {
                    "provider": "mercadolivre",
                    "store": "Mercado Livre",
                    "title": title,
                    "url": link,
                    "canonical_url": canonical_url,
                    "selected": False,
                    "product_id": product_id,
                    "affiliate_detected": bool(_has_meli_affiliate_marker(link)),
                    "match_found": False,
                    "match_reason": (
                        "Link sem marcador oficial de afiliado."
                        if not _has_meli_affiliate_marker(link)
                        else "Nenhuma oferta cadastrada bateu com este link."
                    ),
                }
            )
            continue

        results.append(
            {
                "provider": "mercadolivre",
                "store": "Mercado Livre",
                "title": title,
                "url": link,
                "canonical_url": canonical_url,
                "selected": bool(_has_meli_affiliate_marker(link)),
                "product_id": product_id,
                "affiliate_detected": bool(_has_meli_affiliate_marker(link)),
                "match_found": True,
                "match_reason": reason,
                "matched_offer_id": int(matched["id"]),
                "matched_offer_title": matched["titulo"],
                "matched_offer_slug": matched["slug"],
                "matched_offer_active": int(matched.get("ativo") or 0),
                "matched_offer_url": matched.get("url_afiliado") or "",
            }
        )

    return results


def relink_mercadolivre_existing_offers(db, items: list[dict]) -> dict[str, int]:
    summary = {"processed": 0, "updated": 0, "reactivated": 0, "skipped": 0, "invalid": 0}
    for item in items:
        summary["processed"] += 1
        if not item.get("selected"):
            summary["skipped"] += 1
            continue

        matched_offer_id = item.get("matched_offer_id")
        affiliate_detected = bool(item.get("affiliate_detected"))
        source_url = str(item.get("url") or "").strip()
        if not matched_offer_id or not affiliate_detected or not _has_meli_affiliate_marker(source_url):
            summary["invalid"] += 1
            continue

        was_active = int(item.get("matched_offer_active") or 0)
        db.execute(
            UPDATE_OFFER_SQL,
            {"id": int(matched_offer_id), "url_afiliado": source_url, "ativo": 1},
        )
        summary["updated"] += 1
        if was_active != 1:
            summary["reactivated"] += 1

    return summary
