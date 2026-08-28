import argparse
import json
import re
import sys
import time
from base64 import urlsafe_b64decode
from datetime import datetime
from html import unescape
from pathlib import Path
from urllib.parse import quote, urlparse, parse_qs, urlencode, urlunparse

import httpx
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.database import SessionLocal
from app.collectors.shopee import (
    ShopeeBlockedError,
    enrich_shopee_offers_with_media,
    preview_shopee_affiliate_links,
    resolve_shopee_offer_for_reimport,
    search_shopee_offers_page,
)
from app.collectors.mercadolivre import (
    MELI_API_URL,
    _build_auth_headers,
    _extract_meli_item_id,
    _extract_meli_product_id,
    _refresh_access_token_if_needed,
)
from app.services.manual_link_import import _fetch_best_html_for_provider
from app.main import (
    execute_deploy_automation,
    execute_deploy_site,
    execute_import_run,
    execute_social_run,
    execute_youtube_auto_cut_publish,
    execute_youtube_cut_private_test,
    execute_youtube_cuts_analyze,
    execute_youtube_cuts_process,
    execute_youtube_cut_publish,
    execute_youtube_trends_themes,
)
from app.services.dashboard_data import record_execution_error, record_execution_start, record_execution_success
from app.services.manual_file_import import preview_amazon_txt_file, preview_mercadolivre_txt_file, preview_shopee_csv_file
from app.services.manual_link_import import preview_manual_affiliate_links
from app.services.normalize import normalize_offer
from app.services.publish import publish_offer
from app.services.shopee_video import attach_generated_package_video, build_shopee_video_package
from app.services.store_maintenance import cleanup_shopee_offer_pool, repair_mercadolivre_product_links
from app.services.youtube_cuts import rerender_youtube_cut


def _emit(payload: dict, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=True, default=str))
    return exit_code


def _apply_shopee_block_summary(summary: dict, exc: ShopeeBlockedError) -> None:
    retry_after_seconds = int(exc.retry_after_seconds or 0) if getattr(exc, "retry_after_seconds", None) is not None else None
    summary["blocked"] = True
    summary["blocked_source"] = str(getattr(exc, "source", "shopee") or "shopee")
    summary["blocked_message"] = str(exc)
    if retry_after_seconds is not None:
        summary["blocked_retry_after_seconds"] = retry_after_seconds


def _is_mysql_lock_timeout(exc: Exception) -> bool:
    message = str(exc or "").lower()
    return "lock wait timeout exceeded" in message or "deadlock found" in message or "(1205" in message or "(1213" in message


def _update_existing_offer_with_retry(db, offer_id: int, normalized, *, max_attempts: int = 3) -> None:
    last_error: Exception | None = None
    for attempt in range(1, max(1, int(max_attempts or 3)) + 1):
        try:
            _update_existing_offer(db, offer_id, normalized)
            db.commit()
            return
        except OperationalError as exc:
            db.rollback()
            last_error = exc
            if not _is_mysql_lock_timeout(exc) or attempt >= max_attempts:
                raise
            time.sleep(min(attempt, 3))
        except Exception:
            db.rollback()
            raise
    if last_error is not None:
        raise last_error


def _import_items(items: list[dict], actor_user_id: int | None = None, actor_login: str | None = None) -> dict:
    db = SessionLocal()
    summary = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "items": []}
    try:
        for item in items:
            store = (item.get("store") or "").strip() or "Oferta"
            normalized = normalize_offer(item, store, item.get("affiliate_code"))
            action = publish_offer(
                db,
                normalized,
                actor_user_id=actor_user_id,
                actor_login=actor_login,
            )
            summary["processed"] += 1
            summary[action] += 1
            summary["items"].append(
                {
                    "title": item.get("title"),
                    "store": store,
                    "price": item.get("price"),
                    "action": action,
                }
            )
        db.commit()
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _repair_shopee_media(offer_ids: list[int] | None = None, latest: int | None = None) -> dict:
    db = SessionLocal()
    summary = {"processed": 0, "created": 0, "updated": 0, "skipped": 0, "invalid": 0, "with_video": 0, "without_video": 0, "items": [], "blocked": False}
    try:
        if offer_ids:
            placeholders = ", ".join(f":offer_id_{index}" for index, _ in enumerate(offer_ids))
            params = {f"offer_id_{index}": int(offer_id) for index, offer_id in enumerate(offer_ids)}
            rows = db.execute(
                text(
                    f"""
                    SELECT id, titulo, descricao, preco, preco_antigo, url_afiliado, imagem_url, imagem_urls_json, video_urls_json, categoria, tags, loja
                    FROM ofertas
                    WHERE loja = 'Shopee' AND id IN ({placeholders})
                    ORDER BY COALESCE(atualizado_em, criado_em) DESC, id DESC
                    """
                ),
                params,
            ).mappings().all()
        else:
            rows = db.execute(
                text(
                    """
                    SELECT id, titulo, descricao, preco, preco_antigo, url_afiliado, imagem_url, imagem_urls_json, video_urls_json, categoria, tags, loja
                    FROM ofertas
                    WHERE loja = 'Shopee'
                    ORDER BY COALESCE(atualizado_em, criado_em) DESC, id DESC
                    LIMIT :limit_value
                    """
                ),
                {"limit_value": max(1, int(latest or 4))},
            ).mappings().all()

        items: list[dict] = []
        for row in rows:
            image_urls = json.loads(str(row["imagem_urls_json"])) if row.get("imagem_urls_json") else []
            video_urls = json.loads(str(row["video_urls_json"])) if row.get("video_urls_json") else []
            items.append(
                {
                    "id": int(row["id"]),
                    "title": str(row["titulo"] or ""),
                    "description": str(row["descricao"] or ""),
                    "price": float(row["preco"] or 0),
                    "old_price": float(row["preco_antigo"]) if row.get("preco_antigo") not in (None, "") else None,
                    "url": str(row["url_afiliado"] or ""),
                    "canonical_url": str(row["url_afiliado"] or ""),
                    "image": str(row["imagem_url"] or ""),
                    "image_urls": image_urls if isinstance(image_urls, list) else [],
                    "video_urls": video_urls if isinstance(video_urls, list) else [],
                    "category": str(row["categoria"] or "ofertas"),
                    "tags": str(row["tags"] or "shopee"),
                    "store": str(row["loja"] or "Shopee"),
                    "provider": "shopee",
                }
            )

        for item in items:
            try:
                merged = resolve_shopee_offer_for_reimport(item)
            except ShopeeBlockedError as exc:
                _apply_shopee_block_summary(summary, exc)
                break
            existing_row = next((row for row in rows if int(row["id"]) == int(item["id"])), None)
            if not existing_row:
                summary["invalid"] += 1
                continue

            candidate = _build_refresh_item(dict(existing_row), merged, max_images=5)
            normalized = normalize_offer(candidate, "Shopee", candidate.get("affiliate_code"))
            try:
                _update_existing_offer_with_retry(db, int(item["id"]), normalized)
            except OperationalError as exc:
                summary["skipped"] += 1
                summary["items"].append(
                    {
                        "offer_id": item["id"],
                        "title": normalized.titulo,
                        "status": "skipped",
                        "error": "Oferta bloqueada no banco durante a gravacao. Tente novamente em instantes.",
                    }
                )
                if not _is_mysql_lock_timeout(exc):
                    raise
                continue
            has_video = bool(normalized.video_urls) or "offer_video_url:" in str(normalized.tags or "") or "shopee_video_url:" in str(normalized.tags or "")
            summary["processed"] += 1
            summary["updated"] += 1
            if has_video:
                summary["with_video"] += 1
            else:
                summary["without_video"] += 1
            summary["items"].append(
                {
                    "offer_id": item["id"],
                    "title": normalized.titulo,
                    "images": len(normalized.imagem_urls or []),
                    "videos": len(normalized.video_urls or []),
                    "has_video": has_video,
                    "status": "updated",
                }
            )
        return summary
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


REFRESH_EXISTING_OFFER_SQL = text(
    """
    UPDATE ofertas
    SET titulo = :titulo,
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
        imagem_urls_json = :imagem_urls_json,
        video_urls_json = :video_urls_json,
        categoria = :categoria,
        tags = :tags,
        destaque = :destaque,
        ativo = :ativo,
        atualizado_em = NOW()
    WHERE id = :id
    """
)


def _decode_url_json(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item or "").strip() for item in value if str(item or "").strip()]
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item or "").strip() for item in decoded if str(item or "").strip()]


def _offer_has_video_state(row: dict) -> bool:
    tags = str(row.get("tags") or "")
    if "offer_video_url:" in tags or "shopee_video_url:" in tags:
        return True
    return bool(_decode_url_json(row.get("video_urls_json")))


def _normalize_store_key(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw in {"mercado livre", "mercadolivre", "meli"}:
        return "mercadolivre"
    return raw


def _append_tags(current: str | None, extras: list[str]) -> str:
    tags = [str(part or "").strip() for part in str(current or "").split(",") if str(part or "").strip()]
    for extra in extras:
        normalized = str(extra or "").strip()
        if normalized and normalized not in tags:
            tags.append(normalized)
    return ",".join(tags)


def _is_meli_short_url(url: str) -> bool:
    return str(url or "").strip().lower().startswith("https://meli.la/") or str(url or "").strip().lower().startswith("http://meli.la/")


def _is_shopee_affiliate_url(url: str) -> bool:
    normalized = str(url or "").strip().lower()
    return "shopee" in normalized and (
        "/opaanlp/" in normalized
        or "utm_medium=affiliates" in normalized
        or "mmp_pid=" in normalized
        or "utm_source=" in normalized
    )


def _decode_tag_url(tags: str | None, prefix: str) -> str:
    normalized_prefix = str(prefix or "").strip()
    if not normalized_prefix:
        return ""

    for tag in str(tags or "").split(","):
        candidate = str(tag or "").strip()
        if not candidate.startswith(normalized_prefix):
            continue
        encoded = candidate[len(normalized_prefix) :].strip()
        if not encoded:
            continue
        padding = len(encoded) % 4
        if padding:
            encoded += "=" * (4 - padding)
        try:
            return urlsafe_b64decode(encoded.encode("ascii")).decode("utf-8").strip()
        except Exception:
            continue
    return ""


def _limit_offer_media(item: dict, max_images: int = 5) -> dict:
    normalized = dict(item)
    image_urls = [str(url or "").strip() for url in (normalized.get("image_urls") or []) if str(url or "").strip()]
    image = str(normalized.get("image") or "").strip()
    if image and image not in image_urls:
        image_urls.insert(0, image)
    image_urls = image_urls[: max(1, int(max_images or 5))]
    if image_urls:
        normalized["image"] = image_urls[0]
        normalized["image_urls"] = image_urls
    elif image:
        normalized["image_urls"] = [image]
    else:
        normalized["image_urls"] = []
    return normalized


def _load_existing_store_offers(
    db,
    *,
    store: str,
    limit: int = 25,
    offer_ids: list[int] | None = None,
    shopee_video_state: str = "all",
) -> list[dict]:
    normalized_store = _normalize_store_key(store)
    params: dict[str, object] = {"store": normalized_store}
    where = ["REPLACE(LOWER(loja), ' ', '') = :store"]
    if normalized_store == "shopee":
        video_sql = "(tags LIKE '%offer_video_url:%' OR tags LIKE '%shopee_video_url:%' OR (video_urls_json IS NOT NULL AND video_urls_json <> '' AND video_urls_json <> '[]'))"
        if shopee_video_state == "with":
            where.append(video_sql)
        elif shopee_video_state == "without":
            where.append(f"NOT {video_sql}")

    if offer_ids:
        placeholders = ", ".join(f":offer_id_{index}" for index, _ in enumerate(offer_ids))
        where.append(f"id IN ({placeholders})")
        for index, offer_id in enumerate(offer_ids):
            params[f"offer_id_{index}"] = int(offer_id)

    sql = f"""
        SELECT id, titulo, descricao, preco, preco_antigo, url_afiliado, imagem_url, imagem_urls_json, video_urls_json, categoria, tags, loja, cupom
        FROM ofertas
        WHERE {' AND '.join(where)}
        ORDER BY COALESCE(atualizado_em, criado_em) ASC, id ASC
    """
    if not offer_ids:
        sql += "\nLIMIT :limit_value"
        params["limit_value"] = max(1, int(limit or 25))
    return [dict(row) for row in db.execute(text(sql), params).mappings().all()]


def _build_refresh_item(existing: dict, refreshed: dict, *, max_images: int = 5) -> dict:
    next_item = _limit_offer_media(dict(refreshed), max_images=max_images)
    current_tags = str(existing.get("tags") or "")
    existing_price = float(existing.get("preco") or 0)
    existing_old_price = float(existing.get("preco_antigo") or 0) if existing.get("preco_antigo") not in (None, "") else None
    next_item["store"] = str(existing.get("loja") or next_item.get("store") or "")
    existing_social_url = _decode_tag_url(current_tags, "meli_social_url:")
    refreshed_social_url = str(next_item.get("social_url") or "").strip()
    if next_item["store"].strip().lower() == "mercado livre":
        refreshed_url = str(next_item.get("url") or "").strip()
        existing_url = str(existing.get("url_afiliado") or "").strip()
        preferred_social_url = refreshed_social_url or existing_social_url
        if _is_meli_short_url(refreshed_url):
            next_item["social_url"] = preferred_social_url or refreshed_social_url or existing_social_url
            next_item["url"] = refreshed_url
        elif _is_meli_short_url(existing_url):
            next_item["social_url"] = preferred_social_url or refreshed_social_url or existing_social_url
            next_item["url"] = existing_url
        elif preferred_social_url:
            next_item["social_url"] = preferred_social_url
            next_item["url"] = preferred_social_url
        else:
            next_item["url"] = str(next_item.get("url") or existing.get("url_afiliado") or "")
    elif next_item["store"].strip().lower() == "shopee":
        refreshed_url = str(next_item.get("url") or "").strip()
        existing_url = str(existing.get("url_afiliado") or "").strip()
        if _is_shopee_affiliate_url(existing_url) and not _is_shopee_affiliate_url(refreshed_url):
            next_item["url"] = existing_url
        else:
            next_item["url"] = refreshed_url or existing_url
    else:
        next_item["url"] = str(next_item.get("url") or existing.get("url_afiliado") or "")
    next_item["canonical_url"] = str(next_item.get("canonical_url") or next_item.get("url") or existing.get("url_afiliado") or "")
    if not str(next_item.get("title") or "").strip() or str(next_item.get("title") or "").strip().lower().startswith("faça login"):
        next_item["title"] = str(existing.get("titulo") or next_item.get("title") or "").strip()
    if not str(next_item.get("description") or "").strip() or str(next_item.get("description") or "").strip().lower().startswith("faça login"):
        next_item["description"] = str(existing.get("descricao") or next_item.get("description") or "").strip()
    if float(next_item.get("price") or 0) <= 0 and existing_price > 0:
        next_item["price"] = existing_price
    if next_item.get("old_price") in (None, "") and existing_old_price and existing_old_price > float(next_item.get("price") or 0):
        next_item["old_price"] = existing_old_price
    if not str(next_item.get("category") or "").strip():
        next_item["category"] = str(existing.get("categoria") or "ofertas")
    if not str(next_item.get("coupon") or "").strip() and str(existing.get("cupom") or "").strip():
        next_item["coupon"] = str(existing.get("cupom") or "")

    if not next_item.get("image_urls"):
        existing_images = _decode_url_json(existing.get("imagem_urls_json"))
        if existing_images:
            next_item["image_urls"] = existing_images[: max(1, int(max_images or 5))]
            next_item["image"] = next_item["image_urls"][0]
        elif str(existing.get("imagem_url") or "").strip():
            next_item["image"] = str(existing.get("imagem_url") or "").strip()
            next_item["image_urls"] = [next_item["image"]]

    preserved_tags = [
        tag.strip()
        for tag in current_tags.split(",")
        if tag.strip().startswith("offer_video_url:")
    ]
    if next_item["store"].strip().lower() == "shopee":
        preserved_tags.extend(
            tag.strip()
            for tag in current_tags.split(",")
            if tag.strip().startswith("shopee_video_url:")
        )

    existing_video_urls = _decode_url_json(existing.get("video_urls_json"))
    if not (next_item.get("video_url") or next_item.get("video_urls")) and existing_video_urls:
        next_item["video_urls"] = existing_video_urls
        next_item["video_url"] = existing_video_urls[0]

    if not str(next_item.get("tags") or "").strip() and current_tags.strip():
        next_item["tags"] = current_tags
    else:
        next_item["tags"] = _append_tags(next_item.get("tags"), preserved_tags)
    return next_item


def _update_existing_offer(db, offer_id: int, normalized) -> None:
    payload = normalized.model_dump()
    payload["id"] = int(offer_id)
    payload["imagem_urls_json"] = json.dumps(normalized.imagem_urls, ensure_ascii=True) if normalized.imagem_urls else None
    payload["video_urls_json"] = json.dumps(normalized.video_urls, ensure_ascii=True) if normalized.video_urls else None
    db.execute(REFRESH_EXISTING_OFFER_SQL, payload)


def _normalize_text_tokens(value: str) -> str:
    normalized = str(value or "").strip().lower()
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return " ".join(normalized.split())


def _is_generic_mercadolivre_title(title: str) -> bool:
    normalized = _normalize_text_tokens(title)
    return normalized in {"", "oferta mercado livre", "mercado livre"}


def _mercadolivre_title_score(expected: str, candidate: str) -> int:
    expected_tokens = set(_normalize_text_tokens(expected).split())
    candidate_tokens = set(_normalize_text_tokens(candidate).split())
    if not expected_tokens or not candidate_tokens:
        return -999
    return (len(expected_tokens & candidate_tokens) * 3) - abs(len(expected_tokens) - len(candidate_tokens))


def _mercadolivre_slugify(value: str) -> str:
    normalized = _normalize_text_tokens(value)
    return normalized.replace(" ", "-").strip("-") or "produto"


def _build_mercadolivre_product_url(product_id: str, title: str) -> str:
    normalized_id = str(product_id or "").strip().upper()
    if not normalized_id.startswith("MLB"):
        return ""
    return f"https://www.mercadolivre.com.br/{_mercadolivre_slugify(title)}/p/{normalized_id}"


def _load_mercadolivre_history_titles(db, offer_ids: list[int]) -> dict[int, str]:
    if not offer_ids:
        return {}

    rows = db.execute(
        text(
            """
            SELECT id, result_json
            FROM automacao_execucoes
            WHERE provider = 'mercadolivre'
              AND modo = 'refresh_existing'
              AND status = 'success'
            ORDER BY id DESC
            """
        )
    ).mappings().all()

    wanted = {int(offer_id) for offer_id in offer_ids}
    resolved: dict[int, str] = {}
    for row in rows:
        raw_result = str(row.get("result_json") or "").strip()
        if not raw_result:
            continue
        try:
            payload = json.loads(raw_result)
        except json.JSONDecodeError:
            continue
        items = [item for item in (payload.get("items") or []) if isinstance(item, dict) and item.get("offer_id")]
        if not items:
            continue

        title_counts: dict[str, int] = {}
        for item in items:
            title_key = _normalize_text_tokens(str(item.get("title") or ""))
            if title_key:
                title_counts[title_key] = title_counts.get(title_key, 0) + 1

        for item in items:
            offer_id = int(item.get("offer_id") or 0)
            if offer_id not in wanted or offer_id in resolved:
                continue
            title = str(item.get("title") or "").strip()
            title_key = _normalize_text_tokens(title)
            if _is_generic_mercadolivre_title(title):
                continue
            if title_counts.get(title_key, 0) >= 4:
                continue
            resolved[offer_id] = title

        if len(resolved) >= len(wanted):
            break

    return resolved


def _clean_mercadolivre_access_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    wid = str((query.get("wid") or [None])[0] or "").strip().upper()
    safe_query: list[tuple[str, str]] = []
    if wid.startswith("MLB"):
        safe_query.append(("wid", wid))
    return urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", urlencode(safe_query), ""))


def _extract_mercadolivre_title_from_html(html_text: str) -> str:
    patterns = [
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
        r'itemprop=["\']price["\'][^>]+content=["\']([\d\.,]+)["\']',
    ]
    title = ""
    for pattern in patterns[:2]:
        match = re.search(pattern, html_text or "", re.IGNORECASE | re.DOTALL)
        if match:
            title = unescape(str(match.group(1) or "").strip())
            break
    title = re.sub(r"\s*-\s*R\$\s*[\d\.,]+.*$", "", title).strip()
    title = re.sub(r"\s*\|\s*Mercado Livre\s*$", "", title, flags=re.IGNORECASE).strip()
    return title


def _extract_mercadolivre_price_from_html(html_text: str) -> float:
    patterns = [
        r'itemprop=["\']price["\'][^>]+content=["\']([\d\.,]+)["\']',
        r'property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']',
        r'"price"\s*:\s*([\d\.]+)',
        r'R\$\s*([\d\.,]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        raw = str(match.group(1) or "").replace(".", "").replace(",", ".")
        try:
            return float(raw)
        except ValueError:
            continue
    return 0.0


def _extract_mercadolivre_old_price_from_html(html_text: str) -> float | None:
    patterns = [
        r'"originalPrice"\s*:\s*([\d\.]+)',
        r'"original_price"\s*:\s*([\d\.]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text or "", re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        try:
            value = float(str(match.group(1) or "0"))
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _extract_mercadolivre_gallery_from_html(html_text: str, max_images: int = 5) -> list[str]:
    urls: list[str] = []
    seen_groups: set[str] = set()
    for raw_url in re.findall(r'https://http2\.mlstatic\.com/[^\s,"\']+\.(?:webp|jpg|jpeg|png)', html_text or "", re.IGNORECASE):
        if "/frontend-assets/" in raw_url:
            continue
        match = re.search(r'(MLA\d+_\d+)', raw_url, re.IGNORECASE)
        group = str(match.group(1) or "").upper() if match else raw_url
        if group in seen_groups:
            continue
        seen_groups.add(group)
        urls.append(raw_url)
        if len(urls) >= max(1, int(max_images or 5)):
            break
    return urls


def _extract_mercadolivre_video_urls_from_html(html_text: str) -> list[str]:
    urls: list[str] = []
    for raw_url in re.findall(r'https://[^"\']+\.mp4[^"\']*', html_text or "", re.IGNORECASE):
        cleaned = unescape(str(raw_url or "").strip())
        if cleaned not in urls:
            urls.append(cleaned)
    return urls


def _search_mercadolivre_candidate_products(title: str, limit: int = 8) -> list[dict]:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        return []

    try:
        access_token = _refresh_access_token_if_needed()
    except Exception:
        access_token = ""
    if not access_token:
        return []

    search_terms: list[str] = []
    ascii_title = _normalize_text_tokens(normalized_title)
    for candidate in (
        normalized_title,
        ascii_title,
        " ".join(normalized_title.split()[:10]),
        " ".join(normalized_title.split()[:6]),
        " ".join(ascii_title.split()[:10]),
        " ".join(ascii_title.split()[:6]),
    ):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in search_terms:
            search_terms.append(candidate)

    results: list[dict] = []
    seen_ids: set[str] = set()
    with httpx.Client(timeout=20, headers=_build_auth_headers(access_token), follow_redirects=True) as client:
        for term in search_terms:
            try:
                response = client.get(
                    f"{MELI_API_URL}/products/search",
                    params={"q": term, "site_id": "MLB", "limit": max(3, min(int(limit or 8), 10))},
                )
                response.raise_for_status()
            except Exception:
                continue

            payload = response.json() or {}
            for row in payload.get("results") or []:
                product_id = str((row or {}).get("id") or "").strip().upper()
                product_name = str((row or {}).get("name") or "").strip()
                if not product_id.startswith("MLB") or not product_name or product_id in seen_ids:
                    continue
                seen_ids.add(product_id)
                results.append(
                    {
                        "product_id": product_id,
                        "title": product_name,
                        "url": _build_mercadolivre_product_url(product_id, product_name),
                        "image": str((((row or {}).get("pictures") or [{}])[0] or {}).get("url") or "").strip(),
                        "raw": row,
                    }
                )
                if len(results) >= max(1, int(limit or 8)):
                    return results
    return results


def _collect_mercadolivre_media_urls(payload: object, *, image_urls: list[str], video_urls: list[str]) -> None:
    if isinstance(payload, dict):
        candidate_url = str(payload.get("secure_url") or payload.get("url") or "").strip()
        if not candidate_url:
            candidate_url = str(payload.get("secure_thumbnail") or payload.get("thumbnail") or "").strip()
        lowered_candidate = candidate_url.lower()
        if candidate_url.startswith("http") and "mlstatic.com" in lowered_candidate and re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?|$)", lowered_candidate):
            size_token = str(payload.get("max_size") or payload.get("size") or "").strip().lower()
            width = int(payload.get("width") or 0) if str(payload.get("width") or "").strip().isdigit() else 0
            height = int(payload.get("height") or 0) if str(payload.get("height") or "").strip().isdigit() else 0
            if (width <= 0 or height <= 0) and "x" in size_token:
                match = re.search(r"(\d+)\s*x\s*(\d+)", size_token)
                if match:
                    width = int(match.group(1))
                    height = int(match.group(2))
            min_side = 500
            if width >= min_side and height >= min_side and candidate_url not in image_urls:
                image_urls.append(candidate_url)
        for value in payload.values():
            _collect_mercadolivre_media_urls(value, image_urls=image_urls, video_urls=video_urls)
        return

    if isinstance(payload, list):
        for value in payload:
            _collect_mercadolivre_media_urls(value, image_urls=image_urls, video_urls=video_urls)
        return

    if not isinstance(payload, str):
        return

    candidate = str(payload or "").strip()
    if not candidate.startswith("http"):
        return

    lowered = candidate.lower()
    if re.search(r"\.mp4(?:\?|$)", lowered) and candidate not in video_urls:
        video_urls.append(candidate)


def _enrich_mercadolivre_media_with_api(candidate: dict, html_text: str = "", max_images: int = 5) -> dict:
    enriched = dict(candidate)
    canonical_url = str(enriched.get("canonical_url") or enriched.get("url") or "").strip()
    item_id = _extract_meli_item_id(canonical_url) or _extract_meli_item_id(str(enriched.get("url") or ""))
    product_id = _extract_meli_product_id(canonical_url) or _extract_meli_product_id(str(enriched.get("url") or ""))
    if not item_id and not product_id:
        return _limit_offer_media(enriched, max_images=max_images)

    try:
        access_token = _refresh_access_token_if_needed()
    except Exception:
        access_token = ""

    if not access_token:
        return _limit_offer_media(enriched, max_images=max_images)

    headers = _build_auth_headers(access_token)
    image_urls: list[str] = [str(url or "").strip() for url in (enriched.get("image_urls") or []) if str(url or "").strip()]
    video_urls: list[str] = [str(url or "").strip() for url in (enriched.get("video_urls") or []) if str(url or "").strip()]
    if str(enriched.get("image") or "").strip() and str(enriched.get("image") or "").strip() not in image_urls:
        image_urls.insert(0, str(enriched.get("image") or "").strip())

    with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as client:
        if product_id:
            try:
                response = client.get(f"{MELI_API_URL}/products/{product_id}")
                response.raise_for_status()
                payload = response.json()
                _collect_mercadolivre_media_urls(payload, image_urls=image_urls, video_urls=video_urls)
                if not str(enriched.get("title") or "").strip():
                    enriched["title"] = str(payload.get("name") or payload.get("family_name") or "").strip()
                if not str(enriched.get("product_id") or "").strip():
                    enriched["product_id"] = str(payload.get("id") or "").strip() or product_id
            except Exception:
                pass

            try:
                response = client.get(f"{MELI_API_URL}/products/{product_id}/items", params={"limit": 1})
                response.raise_for_status()
                results = (response.json() or {}).get("results") or []
                if results:
                    top_item = results[0] or {}
                    item_id = str(top_item.get("item_id") or "").strip().upper() or item_id
                    if float(enriched.get("price") or 0) <= 0:
                        enriched["price"] = float(top_item.get("price") or 0)
                    if enriched.get("old_price") in (None, "") and top_item.get("original_price"):
                        enriched["old_price"] = float(top_item.get("original_price") or 0)
                    if not str(enriched.get("shipping") or "").strip():
                        shipping = top_item.get("shipping") or {}
                        if bool(shipping.get("free_shipping")):
                            enriched["shipping"] = "Frete gratis"
                    if not str(enriched.get("category") or "").strip():
                        enriched["category"] = str(top_item.get("category_id") or "").strip() or "ofertas"
            except Exception:
                pass

        if item_id:
            enriched["item_id"] = item_id
            try:
                response = client.get(f"{MELI_API_URL}/items/{item_id}")
                if response.status_code < 400:
                    payload = response.json()
                    _collect_mercadolivre_media_urls(payload, image_urls=image_urls, video_urls=video_urls)
                    permalink = str(payload.get("permalink") or "").strip()
                    if permalink and not str(enriched.get("canonical_url") or "").strip():
                        enriched["canonical_url"] = permalink
                    if not str(enriched.get("image") or "").strip():
                        enriched["image"] = (
                            str(payload.get("secure_thumbnail") or "").strip()
                            or str(payload.get("thumbnail") or "").strip()
                        )
            except Exception:
                pass

    html_video_urls = _extract_mercadolivre_video_urls_from_html(html_text)
    for url in html_video_urls:
        if url not in video_urls:
            video_urls.append(url)

    if image_urls:
        enriched["image_urls"] = image_urls[: max(1, int(max_images or 5))]
        enriched["image"] = enriched["image_urls"][0]
    if video_urls:
        enriched["video_urls"] = video_urls
        enriched["video_url"] = video_urls[0]
    return _limit_offer_media(enriched, max_images=max_images)


def _search_mercadolivre_candidate_urls(title: str, limit: int = 8) -> list[str]:
    normalized_title = str(title or "").strip()
    if not normalized_title:
        return []
    search_terms: list[str] = []
    ascii_title = _normalize_text_tokens(normalized_title)
    for candidate in (
        normalized_title,
        ascii_title,
        " ".join(normalized_title.split()[:8]),
        " ".join(normalized_title.split()[:5]),
        " ".join(ascii_title.split()[:8]),
        " ".join(ascii_title.split()[:5]),
    ):
        candidate = str(candidate or "").strip()
        if candidate and candidate not in search_terms:
            search_terms.append(candidate)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    urls: list[str] = []
    with httpx.Client(timeout=20, headers=headers, follow_redirects=True) as client:
        for term in search_terms:
            search_url = "https://lista.mercadolivre.com.br/" + quote(term.replace(" ", "-"))
            try:
                response = client.get(search_url)
                response.raise_for_status()
            except Exception:
                continue
            html_text = response.text
            for raw_url in re.findall(r'"url":"(https:[^"]*MLB[^"]+)"', html_text, re.IGNORECASE):
                candidate = (
                    str(raw_url or "")
                    .replace("\\u002F", "/")
                    .replace("\\u0026", "&")
                    .replace("\\u003D", "=")
                    .replace("\\u002E", ".")
                    .replace("\\/", "/")
                    .strip()
                )
                candidate = candidate.split("#", 1)[0].strip()
                if "/p/MLB" not in candidate and "/MLB-" not in candidate:
                    continue
                if candidate in urls:
                    continue
                urls.append(candidate)
                if len(urls) >= max(1, int(limit or 8)):
                    return urls
    return urls


def _recover_mercadolivre_offer(target_title: str) -> dict | None:
    best_item: dict | None = None
    best_score = -999

    for candidate in _search_mercadolivre_candidate_products(target_title, limit=8)[:5]:
        score = _mercadolivre_title_score(target_title, str(candidate.get("title") or ""))
        recovered = {
            "title": str(candidate.get("title") or target_title).strip(),
            "description": "",
            "price": 0.0,
            "old_price": None,
            "url": str(candidate.get("url") or "").strip(),
            "canonical_url": str(candidate.get("url") or "").strip(),
            "image": str(candidate.get("image") or "").strip(),
            "image_urls": [str(candidate.get("image") or "").strip()] if str(candidate.get("image") or "").strip() else [],
            "video_urls": [],
            "category": "ofertas",
            "tags": "mercadolivre,manual,repair",
            "store": "Mercado Livre",
            "product_id": str(candidate.get("product_id") or "").strip().upper(),
        }
        recovered = _enrich_mercadolivre_media_with_api(recovered, "", max_images=5)
        if float(recovered.get("price") or 0) <= 0:
            score -= 50
        if recovered.get("image_urls"):
            score += min(len(recovered.get("image_urls") or []), 5)
        if score > best_score:
            best_score = score
            best_item = recovered

    if best_item and best_score >= 4:
        return best_item

    candidates = _search_mercadolivre_candidate_urls(target_title, limit=8)
    for candidate_url in candidates[:5]:
        try:
            final_url, html_text = _fetch_best_html_for_provider(candidate_url, "mercadolivre")
        except Exception:
            continue

        parsed_title = _extract_mercadolivre_title_from_html(html_text)
        parsed_price = _extract_mercadolivre_price_from_html(html_text)
        gallery = _extract_mercadolivre_gallery_from_html(html_text, max_images=5)
        product_access_url = _clean_mercadolivre_access_url(final_url or candidate_url)
        score = _mercadolivre_title_score(target_title, parsed_title)
        if parsed_price <= 0:
            score -= 50
        if gallery:
            score += min(len(gallery), 5)
        if score <= best_score:
            continue

        best_score = score
        recovered = {
            "title": parsed_title or target_title,
            "description": "",
            "price": parsed_price,
            "old_price": _extract_mercadolivre_old_price_from_html(html_text),
            "url": product_access_url,
            "canonical_url": str(final_url or candidate_url),
            "image": gallery[0] if gallery else "",
            "image_urls": gallery,
            "video_urls": _extract_mercadolivre_video_urls_from_html(html_text),
            "category": "ofertas",
            "tags": "mercadolivre,manual,repair",
            "store": "Mercado Livre",
        }
        recovered = _enrich_mercadolivre_media_with_api(recovered, html_text, max_images=5)
        best_item = recovered

    return best_item


def _repair_mercadolivre_broken_offers(limit: int | None = None) -> dict:
    db = SessionLocal()
    summary = {
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "invalid": 0,
        "with_video": 0,
        "without_video": 0,
        "items": [],
        "backup_table": "",
    }
    try:
        where_sql = "LOWER(loja) = 'mercado livre' AND url_afiliado LIKE '%social-profile-middleend%'"
        rows_sql = f"""
            SELECT id, titulo, descricao, preco, preco_antigo, url_afiliado, imagem_url, imagem_urls_json, video_urls_json, categoria, tags, loja, cupom
            FROM ofertas
            WHERE {where_sql}
            ORDER BY id DESC
        """
        if limit:
            rows_sql += "\nLIMIT :limit_value"
            rows = db.execute(text(rows_sql), {"limit_value": max(1, int(limit))}).mappings().all()
        else:
            rows = db.execute(text(rows_sql)).mappings().all()

        target_ids = [int(row["id"]) for row in rows]
        history_titles = _load_mercadolivre_history_titles(db, target_ids)
        backup_table = f"ofertas_backup_ml_repair_before_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        summary["backup_table"] = backup_table
        db.execute(text(f"CREATE TABLE `{backup_table}` AS SELECT * FROM ofertas WHERE {where_sql}"))

        run_id = record_execution_start(
            db,
            tipo="maintenance",
            provider="mercadolivre",
            modo="repair_broken",
            requested_count=len(rows),
            payload={"limit": limit or 0, "backup_table": backup_table},
        )

        for row in rows:
            offer_id = int(row["id"])
            summary["processed"] += 1
            recovered_title = history_titles.get(offer_id) or str(row.get("titulo") or "").strip()
            if _is_generic_mercadolivre_title(recovered_title):
                summary["invalid"] += 1
                summary["items"].append({"offer_id": offer_id, "status": "invalid", "title": recovered_title, "error": "Sem titulo historico confiavel"})
                continue

            candidate = _recover_mercadolivre_offer(recovered_title)
            if not candidate:
                summary["skipped"] += 1
                summary["items"].append({"offer_id": offer_id, "status": "skipped", "title": recovered_title, "error": "Nao encontrei um link confiavel na busca HTML"})
                continue

            candidate = _build_refresh_item(dict(row), candidate, max_images=5)
            normalized = normalize_offer(candidate, "Mercado Livre", candidate.get("affiliate_code"))
            _update_existing_offer(db, offer_id, normalized)
            has_video = bool(normalized.video_urls)
            summary["updated"] += 1
            if has_video:
                summary["with_video"] += 1
            else:
                summary["without_video"] += 1
            summary["items"].append(
                {
                    "offer_id": offer_id,
                    "status": "updated",
                    "title": normalized.titulo,
                    "url": normalized.url_afiliado,
                    "images": len(normalized.imagem_urls or []),
                    "videos": len(normalized.video_urls or []),
                }
            )

        db.commit()
        record_execution_success(db, run_id, processed_count=int(summary["processed"]), result=summary)
        return summary
    except Exception as exc:
        db.rollback()
        try:
            record_execution_error(db, run_id, error_message=str(exc), result=summary)  # type: ignore[name-defined]
        except Exception:
            pass
        raise
    finally:
        db.close()


def _refresh_existing_store_offers(
    *,
    store: str,
    limit: int = 25,
    offer_ids: list[int] | None = None,
    shopee_video_state: str = "all",
    max_images: int = 5,
) -> dict:
    normalized_store = _normalize_store_key(store)
    provider_label = {
        "shopee": "Shopee",
        "amazon": "Amazon",
        "mercadolivre": "Mercado Livre",
    }.get(normalized_store, store)
    db = SessionLocal()
    requested_count = len(offer_ids or []) if offer_ids else max(1, int(limit or 25))
    run_id = record_execution_start(
        db,
        tipo="import",
        provider=normalized_store,
        modo="refresh_existing",
        requested_count=requested_count,
        payload={
            "store": normalized_store,
            "offer_ids": list(offer_ids or []),
            "limit": max(1, int(limit or 25)),
            "shopee_video_state": shopee_video_state,
            "max_images": max(1, int(max_images or 5)),
        },
    )
    summary = {
        "run_id": run_id,
        "store": provider_label,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "invalid": 0,
        "with_video": 0,
        "without_video": 0,
        "blocked": False,
        "items": [],
    }
    try:
        rows = _load_existing_store_offers(
            db,
            store=provider_label,
            limit=max(1, int(limit or 25)),
            offer_ids=offer_ids or None,
            shopee_video_state=shopee_video_state,
        )
        for row in rows:
            summary["processed"] += 1
            current_url = str(row.get("url_afiliado") or "").strip()
            if not current_url:
                summary["invalid"] += 1
                continue

            try:
                if normalized_store == "shopee":
                    items = preview_shopee_affiliate_links([current_url])
                else:
                    items = preview_manual_affiliate_links([current_url])
            except ShopeeBlockedError as exc:
                _apply_shopee_block_summary(summary, exc)
                break
            except Exception as exc:  # noqa: BLE001
                summary["invalid"] += 1
                summary["items"].append(
                    {
                        "offer_id": int(row["id"]),
                        "title": str(row.get("titulo") or ""),
                        "status": "invalid",
                        "error": str(exc),
                    }
                )
                continue

            candidate = dict(items[0]) if items else {}
            if normalized_store == "shopee":
                media_seed = dict(candidate) if candidate else {
                    "title": str(row.get("titulo") or ""),
                    "description": str(row.get("descricao") or ""),
                    "price": float(row.get("preco") or 0),
                    "old_price": float(row["preco_antigo"]) if row.get("preco_antigo") not in (None, "") else None,
                    "url": current_url,
                    "canonical_url": current_url,
                    "image": str(row.get("imagem_url") or ""),
                    "image_urls": _decode_url_json(row.get("imagem_urls_json")),
                    "video_urls": _decode_url_json(row.get("video_urls_json")),
                    "category": str(row.get("categoria") or "ofertas"),
                    "tags": str(row.get("tags") or "shopee"),
                    "store": "Shopee",
                }
                try:
                    candidate = resolve_shopee_offer_for_reimport(media_seed)
                except ShopeeBlockedError as exc:
                    _apply_shopee_block_summary(summary, exc)
                    break
                except Exception:  # noqa: BLE001
                    candidate = media_seed
            elif normalized_store == "mercadolivre" and candidate:
                try:
                    candidate = _enrich_mercadolivre_media_with_api(candidate, max_images=max_images)
                except Exception:
                    pass

            if not candidate:
                summary["skipped"] += 1
                continue

            candidate = _build_refresh_item(row, candidate, max_images=max_images)
            if float(candidate.get("price") or 0) <= 0:
                summary["skipped"] += 1
                continue

            normalized = normalize_offer(candidate, provider_label, candidate.get("affiliate_code"))
            try:
                _update_existing_offer_with_retry(db, int(row["id"]), normalized)
            except OperationalError as exc:
                summary["skipped"] += 1
                summary["items"].append(
                    {
                        "offer_id": int(row["id"]),
                        "title": normalized.titulo,
                        "status": "skipped",
                        "error": "Oferta bloqueada no banco durante a gravacao. Tente novamente em instantes.",
                    }
                )
                if not _is_mysql_lock_timeout(exc):
                    raise
                continue
            has_video = bool(normalized.video_urls) or "offer_video_url:" in str(normalized.tags or "") or "shopee_video_url:" in str(normalized.tags or "")
            summary["updated"] += 1
            if has_video:
                summary["with_video"] += 1
            else:
                summary["without_video"] += 1
            summary["items"].append(
                {
                    "offer_id": int(row["id"]),
                    "title": normalized.titulo,
                    "status": "updated",
                    "price": normalized.preco,
                    "images": len(normalized.imagem_urls or []),
                    "videos": len(normalized.video_urls or []),
                    "has_video": has_video,
                }
            )

        record_execution_success(db, run_id, processed_count=int(summary["processed"]), result=summary)
        return summary
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        record_execution_error(db, run_id, error_message=str(exc), result=summary)
        raise
    finally:
        db.close()


def _refresh_catalog(
    *,
    amazon_limit: int = 0,
    mercadolivre_limit: int = 0,
    shopee_limit: int = 0,
    shopee_video_state: str = "all",
    max_images: int = 5,
) -> dict:
    stores_to_run = [
        ("Amazon", amazon_limit),
        ("Mercado Livre", mercadolivre_limit),
        ("Shopee", shopee_limit),
    ]
    results = []
    totals = {
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "invalid": 0,
        "with_video": 0,
        "without_video": 0,
    }
    for store_name, limit_val in stores_to_run:
        actual_limit = None if limit_val in (0, None, "") else int(limit_val)
        try:
            res = _refresh_existing_store_offers(
                store=store_name,
                limit=actual_limit,
                shopee_video_state=shopee_video_state,
                max_images=max_images,
            )
            results.append({"store": store_name, "ok": True, "limit": limit_val, "result": res})
            totals["processed"] += int(res.get("processed") or 0)
            totals["updated"] += int(res.get("updated") or 0)
            totals["skipped"] += int(res.get("skipped") or 0)
            totals["invalid"] += int(res.get("invalid") or 0)
            totals["with_video"] += int(res.get("with_video") or 0)
            totals["without_video"] += int(res.get("without_video") or 0)
        except Exception as exc:  # noqa: BLE001
            results.append({"store": store_name, "ok": False, "limit": limit_val, "error": str(exc)})

    return {"stores": results, "totals": totals}


def main() -> int:
    parser = argparse.ArgumentParser(description="Executa jobs da automacao via CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh_catalog_parser = subparsers.add_parser("refresh-catalog", help="Reimporta e atualiza o catalogo de todas as lojas.")
    refresh_catalog_parser.add_argument("--amazon-limit", type=int, default=0)
    refresh_catalog_parser.add_argument("--mercadolivre-limit", type=int, default=0)
    refresh_catalog_parser.add_argument("--shopee-limit", type=int, default=0)
    refresh_catalog_parser.add_argument("--shopee-video-state", choices=["all", "with", "without"], default="all")
    refresh_catalog_parser.add_argument("--max-images", type=int, default=5)

    social_parser = subparsers.add_parser("social", help="Publica ofertas nas redes sociais.")
    social_parser.add_argument("--platform", required=True)
    social_parser.add_argument("--mode", default="reel_story")
    social_parser.add_argument("--limit", type=int, default=1)
    social_parser.add_argument("--offer-id", dest="offer_ids", action="append", type=int, default=[])

    shopee_video_parser = subparsers.add_parser("shopee-video-package", help="Gera pacote profissional para Shopee Video.")
    shopee_video_parser.add_argument("--draft-id", type=int, default=None)
    shopee_video_parser.add_argument("--offer-id", type=int, default=None)

    shopee_video_attach_parser = subparsers.add_parser("shopee-video-attach-generated", help="Aplica o video gerado do pacote na oferta.")
    shopee_video_attach_parser.add_argument("--draft-id", type=int, required=True)

    import_parser = subparsers.add_parser("import", help="Roda importadores configurados.")
    import_parser.add_argument("--provider", dest="providers", action="append", default=[])
    import_parser.add_argument("--limit", type=int, default=None)
    import_parser.add_argument("--keyword", default=None)

    shopee_preview_parser = subparsers.add_parser("shopee-preview", help="Busca produtos da Shopee com paginacao.")
    shopee_preview_parser.add_argument("--keyword", required=True)
    shopee_preview_parser.add_argument("--page", type=int, default=1)
    shopee_preview_parser.add_argument("--limit", type=int, default=12)

    import_file_parser = subparsers.add_parser("import-file", help="Importa um arquivo manual.")
    import_file_parser.add_argument("--kind", required=True, choices=["shopee_csv", "amazon_txt", "mercadolivre_txt"])
    import_file_parser.add_argument("--input-file", required=True)
    import_file_parser.add_argument("--actor-user-id", type=int, default=None)
    import_file_parser.add_argument("--actor-login", default=None)

    import_links_parser = subparsers.add_parser("import-links", help="Importa links colados manualmente.")
    import_links_parser.add_argument("--input-file", required=True)
    import_links_parser.add_argument("--actor-user-id", type=int, default=None)
    import_links_parser.add_argument("--actor-login", default=None)

    import_shopee_selected_parser = subparsers.add_parser("import-shopee-selected", help="Importa itens selecionados da busca Shopee preservando dados da API.")
    import_shopee_selected_parser.add_argument("--input-file", required=True)
    import_shopee_selected_parser.add_argument("--actor-user-id", type=int, default=None)
    import_shopee_selected_parser.add_argument("--actor-login", default=None)

    repair_shopee_media_parser = subparsers.add_parser("repair-shopee-media", help="Reenriquece ofertas da Shopee com galeria e video.")
    repair_shopee_media_parser.add_argument("--offer-id", dest="offer_ids", action="append", type=int, default=[])
    repair_shopee_media_parser.add_argument("--latest", type=int, default=None)

    cleanup_shopee_parser = subparsers.add_parser("cleanup-shopee-offers", help="Valida links da Shopee e mantem apenas os itens mais recentes.")
    cleanup_shopee_parser.add_argument("--keep-latest", type=int, default=500)
    cleanup_shopee_parser.add_argument("--skip-validate", action="store_true")

    refresh_existing_parser = subparsers.add_parser("refresh-existing-offers", help="Reimporta ofertas ja cadastradas de uma loja.")
    refresh_existing_parser.add_argument("--store", required=True, choices=["shopee", "amazon", "mercadolivre"])
    refresh_existing_parser.add_argument("--limit", type=int, default=25)
    refresh_existing_parser.add_argument("--offer-id", dest="offer_ids", action="append", type=int, default=[])
    refresh_existing_parser.add_argument("--shopee-video-state", choices=["all", "with", "without"], default="all")
    refresh_existing_parser.add_argument("--max-images", type=int, default=5)

    repair_meli_broken_parser = subparsers.add_parser("repair-mercadolivre-broken-offers", help="Recupera ofertas do Mercado Livre com link storefront quebrado.")
    repair_meli_broken_parser.add_argument("--limit", type=int, default=None)

    repair_meli_product_links_parser = subparsers.add_parser("repair-mercadolivre-product-links", help="Corrige links de produto do Mercado Livre salvos como perfil/lista.")
    repair_meli_product_links_parser.add_argument("--only-inactive", action="store_true")

    subparsers.add_parser("deploy-automation", help="Envia automacao_ofertas via SFTP.")
    subparsers.add_parser("deploy-site", help="Envia public_html via SFTP.")

    yt_analyze_parser = subparsers.add_parser("youtube-cuts-analyze", help="Analisa um video do YouTube para cortes.")
    yt_analyze_parser.add_argument("--url", required=True)

    yt_process_parser = subparsers.add_parser("youtube-cuts-process", help="Gera cortes de um video do YouTube.")
    yt_process_parser.add_argument("--url", required=True)
    yt_process_parser.add_argument("--limit", type=int, default=5)
    yt_process_parser.add_argument("--mode", default="short")
    yt_process_parser.add_argument("--selection-strategy", default="gemini_heuristica")
    yt_process_parser.add_argument("--risk-profile", default="default")
    yt_process_parser.add_argument("--channel-profile-id", type=int, default=None)
    yt_process_parser.add_argument("--no-burn-subtitles", action="store_true")

    yt_private_test_parser = subparsers.add_parser("youtube-cut-private-test", help="Gera um short com preset conservador e sobe como privado para revisao.")
    yt_private_test_parser.add_argument("--url", required=True)
    yt_private_test_parser.add_argument("--limit", type=int, default=3)
    yt_private_test_parser.add_argument("--selection-strategy", default="gemini_heuristica")
    yt_private_test_parser.add_argument("--channel-profile-id", type=int, default=None)
    yt_private_test_parser.add_argument("--no-burn-subtitles", action="store_true")

    yt_publish_parser = subparsers.add_parser("youtube-cut-publish", help="Publica um corte gerado no YouTube.")
    yt_publish_parser.add_argument("--job-id", required=True)
    yt_publish_parser.add_argument("--cut-id", type=int, required=True)
    yt_publish_parser.add_argument("--title", default=None)
    yt_publish_parser.add_argument("--description", default=None)
    yt_publish_parser.add_argument("--privacy-status", default="public")
    yt_publish_parser.add_argument("--publish-at", default=None)
    yt_publish_parser.add_argument("--mode", default="short")
    yt_publish_parser.add_argument("--channel-profile-id", type=int, default=None)

    yt_rerender_parser = subparsers.add_parser("youtube-cut-rerender", help="Regera um corte curto com enquadramento manual.")
    yt_rerender_parser.add_argument("--job-id", required=True)
    yt_rerender_parser.add_argument("--cut-id", type=int, required=True)
    yt_rerender_parser.add_argument("--framing", default="auto")

    yt_trends_parser = subparsers.add_parser("youtube-trends-themes", help="Busca videos recentes em alta para virar corte.")
    yt_trends_parser.add_argument("--recent-limit", type=int, default=4)
    yt_trends_parser.add_argument("--videos-per-topic", type=int, default=4)
    yt_trends_parser.add_argument("--channel-profile-id", type=int, default=None)

    yt_auto_publish_parser = subparsers.add_parser("youtube-auto-cut-publish", help="Seleciona um video do radar, gera o melhor corte e publica no YouTube.")
    yt_auto_publish_parser.add_argument("--channel-profile-id", type=int, default=None)
    yt_auto_publish_parser.add_argument("--channel-profile-name", default=None)
    yt_auto_publish_parser.add_argument("--recent-limit", type=int, default=8)
    yt_auto_publish_parser.add_argument("--videos-per-topic", type=int, default=5)
    yt_auto_publish_parser.add_argument("--cut-limit", type=int, default=5)
    yt_auto_publish_parser.add_argument("--retry-candidates", type=int, default=4)
    yt_auto_publish_parser.add_argument("--lookback-days", type=int, default=14)
    yt_auto_publish_parser.add_argument("--selection-strategy", default="gemini_heuristica")

    args = parser.parse_args()

    try:
        if args.command == "refresh-catalog":
            result = _refresh_catalog(
                amazon_limit=args.amazon_limit,
                mercadolivre_limit=args.mercadolivre_limit,
                shopee_limit=args.shopee_limit,
                shopee_video_state=args.shopee_video_state,
                max_images=args.max_images,
            )
            return _emit({"ok": True, "command": "refresh-catalog", "result": result})

        if args.command == "social":
            result = execute_social_run(
                platform=args.platform,
                mode=args.mode,
                limit=max(1, int(args.limit)),
                offer_ids=args.offer_ids or None,
            )
            return _emit({"ok": True, "command": "social", "result": result})

        if args.command == "shopee-video-package":
            if args.draft_id is None and args.offer_id is None:
                return _emit({"ok": False, "error": "Informe --draft-id ou --offer-id."}, 1)
            result = build_shopee_video_package(
                draft_id=args.draft_id,
                offer_id=args.offer_id,
            )
            return _emit({"ok": True, "command": "shopee-video-package", "result": result})

        if args.command == "shopee-video-attach-generated":
            result = attach_generated_package_video(draft_id=int(args.draft_id))
            return _emit({"ok": True, "command": "shopee-video-attach-generated", "result": result})

        if args.command == "import":
            result = execute_import_run(args.providers or None, limit=args.limit, keyword=args.keyword)
            return _emit({"ok": True, "command": "import", "result": result})

        if args.command == "shopee-preview":
            result = search_shopee_offers_page(args.keyword, page=max(1, int(args.page)), limit=max(1, int(args.limit)))
            return _emit({"ok": True, "command": "shopee-preview", "result": result})

        if args.command == "import-file":
            input_path = Path(args.input_file)
            if not input_path.is_file():
                return _emit({"ok": False, "error": "Arquivo informado nao encontrado."}, 1)
            content = input_path.read_bytes()
            if args.kind == "shopee_csv":
                items = preview_shopee_csv_file(content, input_path.name)
            elif args.kind == "amazon_txt":
                items = preview_amazon_txt_file(content, input_path.name)
            else:
                items = preview_mercadolivre_txt_file(content, input_path.name)
            items = [item for item in items if bool(item.get("selected", True))]
            result = _import_items(items, actor_user_id=args.actor_user_id, actor_login=args.actor_login)
            return _emit({"ok": True, "command": "import-file", "result": result})

        if args.command == "import-links":
            input_path = Path(args.input_file)
            if not input_path.is_file():
                return _emit({"ok": False, "error": "Arquivo informado nao encontrado."}, 1)
            raw_lines = input_path.read_text(encoding="utf-8", errors="replace").splitlines()
            links = [line.strip() for line in raw_lines if line.strip()]
            items = preview_manual_affiliate_links(links)
            items = [item for item in items if bool(item.get("import_allowed", item.get("affiliate_detected", True)))]
            result = _import_items(items, actor_user_id=args.actor_user_id, actor_login=args.actor_login)
            return _emit({"ok": True, "command": "import-links", "result": result})

        if args.command == "import-shopee-selected":
            input_path = Path(args.input_file)
            if not input_path.is_file():
                return _emit({"ok": False, "error": "Arquivo informado nao encontrado."}, 1)
            try:
                payload = json.loads(input_path.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError:
                return _emit({"ok": False, "error": "Arquivo JSON dos itens selecionados esta invalido."}, 1)
            if not isinstance(payload, list) or not payload:
                return _emit({"ok": False, "error": "Nenhum item selecionado foi enviado para importacao."}, 1)

            base_items: list[dict] = []
            for raw_item in payload:
                if not isinstance(raw_item, dict):
                    continue
                item = dict(raw_item)
                item["store"] = "Shopee"
                item["provider"] = "shopee"
                base_items.append(item)
            if not base_items:
                return _emit({"ok": False, "error": "Nao encontrei itens validos da Shopee para importar."}, 1)

            enriched_items = enrich_shopee_offers_with_media(base_items)
            merged_items: list[dict] = []
            for index, base_item in enumerate(base_items):
                enriched_item = enriched_items[index] if index < len(enriched_items) and isinstance(enriched_items[index], dict) else {}
                merged_item = dict(base_item)
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
                merged_items.append(merged_item)

            result = _import_items(merged_items, actor_user_id=args.actor_user_id, actor_login=args.actor_login)
            return _emit({"ok": True, "command": "import-shopee-selected", "result": result})

        if args.command == "repair-shopee-media":
            if not args.offer_ids and args.latest is None:
                args.latest = 4
            result = _repair_shopee_media(args.offer_ids or None, args.latest)
            return _emit({"ok": True, "command": "repair-shopee-media", "result": result})

        if args.command == "cleanup-shopee-offers":
            db = SessionLocal()
            keep_latest = max(1, int(args.keep_latest or 500))
            validate_links = not bool(args.skip_validate)
            run_id = record_execution_start(
                db,
                tipo="maintenance",
                provider="shopee",
                modo="cleanup",
                requested_count=keep_latest,
                payload={"keep_latest": keep_latest, "validate_links": validate_links},
            )
            try:
                result = cleanup_shopee_offer_pool(
                    db,
                    keep_latest=keep_latest,
                    validate_links=validate_links,
                )
                result = {"run_id": run_id} | result
                record_execution_success(
                    db,
                    run_id,
                    processed_count=int(result.get("processed_total") or 0),
                    result=result,
                )
            except Exception as exc:
                db.rollback()
                record_execution_error(db, run_id, error_message=str(exc))
                raise
            finally:
                db.close()
            return _emit({"ok": True, "command": "cleanup-shopee-offers", "result": result})

        if args.command == "refresh-existing-offers":
            result = _refresh_existing_store_offers(
                store=str(args.store or "").strip(),
                limit=(max(1, int(args.limit)) if args.limit not in (None, "", 0) else None),
                offer_ids=args.offer_ids or None,
                shopee_video_state=str(args.shopee_video_state or "all").strip().lower(),
                max_images=max(1, int(args.max_images or 5)),
            )
            return _emit({"ok": True, "command": "refresh-existing-offers", "result": result})

        if args.command == "repair-mercadolivre-broken-offers":
            result = _repair_mercadolivre_broken_offers(args.limit)
            return _emit({"ok": True, "command": "repair-mercadolivre-broken-offers", "result": result})

        if args.command == "repair-mercadolivre-product-links":
            db = SessionLocal()
            try:
                result = repair_mercadolivre_product_links(db, only_inactive=bool(args.only_inactive))
                db.commit()
            except Exception:
                db.rollback()
                raise
            finally:
                db.close()
            return _emit({"ok": True, "command": "repair-mercadolivre-product-links", "result": result})

        if args.command == "deploy-automation":
            result = execute_deploy_automation()
            return _emit({"ok": True, "command": "deploy-automation", "result": result})

        if args.command == "deploy-site":
            result = execute_deploy_site()
            return _emit({"ok": True, "command": "deploy-site", "result": result})

        if args.command == "youtube-cuts-analyze":
            result = execute_youtube_cuts_analyze(args.url)
            return _emit({"ok": True, "command": "youtube-cuts-analyze", "result": result})

        if args.command == "youtube-cuts-process":
            result = execute_youtube_cuts_process(
                args.url,
                limit=max(1, int(args.limit)),
                mode=args.mode,
                selection_strategy=args.selection_strategy,
                risk_profile=args.risk_profile,
                channel_profile_id=args.channel_profile_id,
                burn_subtitles=not bool(args.no_burn_subtitles),
            )
            return _emit({"ok": True, "command": "youtube-cuts-process", "result": result})

        if args.command == "youtube-cut-private-test":
            result = execute_youtube_cut_private_test(
                args.url,
                limit=max(1, int(args.limit)),
                selection_strategy=args.selection_strategy,
                channel_profile_id=args.channel_profile_id,
                burn_subtitles=not bool(args.no_burn_subtitles),
            )
            return _emit({"ok": True, "command": "youtube-cut-private-test", "result": result})

        if args.command == "youtube-cut-publish":
            result = execute_youtube_cut_publish(
                job_id=args.job_id,
                cut_id=int(args.cut_id),
                title=args.title,
                description=args.description,
                privacy_status=args.privacy_status,
                publish_at=args.publish_at,
                mode=args.mode,
                channel_profile_id=args.channel_profile_id,
            )
            return _emit({"ok": True, "command": "youtube-cut-publish", "result": result})

        if args.command == "youtube-cut-rerender":
            result = rerender_youtube_cut(
                args.job_id,
                int(args.cut_id),
                framing=args.framing,
            )
            return _emit({"ok": True, "command": "youtube-cut-rerender", "result": result})

        if args.command == "youtube-trends-themes":
            result = execute_youtube_trends_themes(
                recent_limit=int(args.recent_limit),
                videos_per_topic=int(args.videos_per_topic),
                channel_profile_id=args.channel_profile_id,
            )
            return _emit({"ok": True, "command": "youtube-trends-themes", "result": result})

        if args.command == "youtube-auto-cut-publish":
            result = execute_youtube_auto_cut_publish(
                channel_profile_id=args.channel_profile_id,
                channel_profile_name=args.channel_profile_name,
                recent_limit=int(args.recent_limit),
                videos_per_topic=int(args.videos_per_topic),
                cut_limit=int(args.cut_limit),
                retry_candidates=int(args.retry_candidates),
                lookback_days=int(args.lookback_days),
                selection_strategy=args.selection_strategy,
            )
            return _emit({"ok": True, "command": "youtube-auto-cut-publish", "result": result})

        return _emit({"ok": False, "error": "Comando nao suportado."}, 2)
    except HTTPException as exc:
        return _emit(
            {
                "ok": False,
                "error": str(exc.detail),
                "status_code": int(exc.status_code),
            },
            1,
        )
    except Exception as exc:  # noqa: BLE001
        return _emit({"ok": False, "error": str(exc)}, 1)


if __name__ == "__main__":
    sys.exit(main())
