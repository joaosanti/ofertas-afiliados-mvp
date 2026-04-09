import os
import re
from typing import Any
from urllib.parse import parse_qs, parse_qsl, unquote, urlencode, urlparse, urlunparse

import httpx
from sqlalchemy import bindparam, text

from app.services.manual_link_import import preview_manual_affiliate_links
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

UPDATE_OFFER_URL_AND_TAGS_SQL = text(
    """
    UPDATE ofertas
    SET url_afiliado = :url_afiliado,
        tags = :tags,
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

SELECT_SHOPEE_OFFER_POOL_SQL = text(
    """
    SELECT id, titulo, url_afiliado, ativo, criado_em, atualizado_em
    FROM ofertas
    WHERE LOWER(loja) = 'shopee'
    ORDER BY COALESCE(atualizado_em, criado_em) DESC, id DESC
    """
)

DELETE_CLICKS_BY_OFFER_IDS_SQL = text("DELETE FROM cliques WHERE oferta_id IN :ids").bindparams(bindparam("ids", expanding=True))
DELETE_OFFERS_BY_IDS_SQL = text("DELETE FROM ofertas WHERE id IN :ids").bindparams(bindparam("ids", expanding=True))


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


def _shopee_check_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _shopee_offer_is_accessible(client: httpx.Client, url: str) -> tuple[bool, str, str, int]:
    candidate = str(url or "").strip()
    if not candidate:
        return False, "sem_url", "", 0

    try:
        response = client.get(candidate, headers=_shopee_check_headers(), follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"erro_http:{str(exc)}", "", 0

    status_code = int(response.status_code or 0)
    final_url = str(response.url or candidate)
    if status_code >= 400:
        return False, f"http_{status_code}", final_url, status_code

    body = (response.text or "")[:12000].lower()
    invalid_markers = (
        "produto não encontrado",
        "produto nao encontrado",
        "produto indisponível",
        "produto indisponivel",
        "página não encontrada",
        "pagina nao encontrada",
        "page not found",
        "item not found",
        "this product is unavailable",
        "produto foi removido",
        "sorry, this product is no longer available",
    )
    if any(marker in body for marker in invalid_markers):
        return False, "conteudo_indisponivel", final_url, status_code

    final_host = (urlparse(final_url).netloc or "").lower()
    if "shopee" not in final_host:
        return False, f"redirecionado:{final_host or 'desconhecido'}", final_url, status_code

    if "<title>shopee</title>" in body and "/product/" not in final_url and "/br/" not in final_url:
        return False, "sem_produto_final", final_url, status_code

    return True, "ok", final_url, status_code


def _delete_offer_ids(db, offer_ids: list[int]) -> int:
    normalized_ids = sorted({int(offer_id) for offer_id in (offer_ids or []) if int(offer_id) > 0})
    if not normalized_ids:
        return 0
    db.execute(DELETE_CLICKS_BY_OFFER_IDS_SQL, {"ids": normalized_ids})
    db.execute(DELETE_OFFERS_BY_IDS_SQL, {"ids": normalized_ids})
    return len(normalized_ids)


def cleanup_shopee_offer_pool(
    db,
    *,
    keep_latest: int = 500,
    validate_links: bool = True,
) -> dict[str, Any]:
    rows = [dict(row) for row in db.execute(SELECT_SHOPEE_OFFER_POOL_SQL).mappings().all()]
    keep_latest = max(1, int(keep_latest or 500))
    kept_rows = rows[:keep_latest]
    trimmed_rows = rows[keep_latest:]

    trimmed_ids = [int(row["id"]) for row in trimmed_rows]
    trimmed_deleted = _delete_offer_ids(db, trimmed_ids)

    checked = 0
    invalid_items: list[dict[str, Any]] = []
    invalid_ids: list[int] = []
    if validate_links and kept_rows:
        with httpx.Client(timeout=20) as client:
            for row in kept_rows:
                checked += 1
                accessible, reason, final_url, status_code = _shopee_offer_is_accessible(client, str(row.get("url_afiliado") or ""))
                if accessible:
                    continue
                invalid_ids.append(int(row["id"]))
                invalid_items.append(
                    {
                        "id": int(row["id"]),
                        "titulo": str(row.get("titulo") or ""),
                        "url": str(row.get("url_afiliado") or ""),
                        "final_url": final_url,
                        "status_code": status_code,
                        "reason": reason,
                    }
                )

    invalid_deleted = _delete_offer_ids(db, invalid_ids)
    return {
        "processed_total": len(rows),
        "kept_latest": keep_latest,
        "checked_links": checked,
        "trimmed_deleted": trimmed_deleted,
        "invalid_deleted": invalid_deleted,
        "invalid_items": invalid_items[:20],
    }


def _sanitize_shopee_affiliate_url(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if "shopee" not in host:
        return raw

    filtered_query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "aff"]
    return urlunparse(parsed._replace(query=urlencode(filtered_query), fragment=""))


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
        "sanitized": 0,
    }

    for row in rows:
        summary["processed"] += 1
        current_url = str(row.get("url_afiliado") or "").strip()
        if not current_url:
            summary["invalid"] += 1
            continue

        fixed_url = _sanitize_shopee_affiliate_url(current_url)

        if not _has_shopee_affiliate_marker(fixed_url):
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
        if fixed_url != current_url:
            summary["sanitized"] += 1
        if int(row.get("ativo") or 0) != 1:
            summary["reactivated"] += 1

    return summary


def _extract_ml_product_id(url: str) -> str | None:
    match = re.search(r"/p/(MLB\d+)", (url or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _is_meli_social_source_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if "mercadolivre" not in host and "mercadolibre" not in host:
        return False
    return "/social/" in path


def _strip_meli_social_url_tag(tags: str | None) -> str | None:
    parts = [str(part or "").strip() for part in str(tags or "").split(",")]
    cleaned = [part for part in parts if part and not part.startswith("meli_social_url:")]
    return ",".join(cleaned) or None


def repair_mercadolivre_product_links(db, only_inactive: bool = False) -> dict[str, int | str]:
    rows = db.execute(
        SELECT_AMAZON_OFFERS_SQL,
        {"store": "Mercado Livre", "only_inactive": 1 if only_inactive else 0},
    ).mappings().all()

    tags_by_id = {
        int(row["id"]): row
        for row in db.execute(
            text(
                """
                SELECT id, tags
                FROM ofertas
                WHERE LOWER(loja) = LOWER('Mercado Livre')
                  AND (:only_inactive = 0 OR ativo = 0)
                """
            ),
            {"only_inactive": 1 if only_inactive else 0},
        ).mappings().all()
    }

    summary = {"processed": 0, "updated": 0, "reactivated": 0, "skipped": 0, "invalid": 0, "sanitized_tags": 0}
    for row in rows:
        summary["processed"] += 1
        offer_id = int(row["id"])
        current_url = str(row.get("url_afiliado") or "").strip()
        current_tags = str((tags_by_id.get(offer_id) or {}).get("tags") or "").strip()
        if not current_url:
            summary["invalid"] += 1
            continue

        next_url = current_url
        if _is_meli_social_source_url(current_url):
            try:
                items = preview_manual_affiliate_links([current_url])
            except Exception:
                items = []
            candidate = dict(items[0]) if items else {}
            candidate_url = str(candidate.get("url") or candidate.get("canonical_url") or "").strip()
            if not candidate_url or _is_meli_social_source_url(candidate_url) or not _has_meli_affiliate_marker(candidate_url):
                summary["invalid"] += 1
                continue
            next_url = candidate_url

        next_tags = _strip_meli_social_url_tag(current_tags)
        next_active = 1
        changed = next_url != current_url or (next_tags or "") != current_tags or int(row.get("ativo") or 0) != next_active
        if not changed:
            summary["skipped"] += 1
            continue

        db.execute(
            UPDATE_OFFER_URL_AND_TAGS_SQL,
            {"id": offer_id, "url_afiliado": next_url, "tags": next_tags, "ativo": next_active},
        )
        summary["updated"] += 1
        if (next_tags or "") != current_tags:
            summary["sanitized_tags"] += 1
        if int(row.get("ativo") or 0) != 1:
            summary["reactivated"] += 1

    return summary


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
