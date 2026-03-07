import csv
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv
from app.integrations.mercadolivre_oauth import refresh_token as oauth_refresh_token

MELI_API_URL = "https://api.mercadolibre.com"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(dotenv_path=ENV_PATH, override=True)


def _env_list(name: str, default_csv: str) -> list[str]:
    raw = os.getenv(name, default_csv)
    return [v.strip() for v in raw.split(',') if v.strip()]


def _build_auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    raw = str(value).strip()
    if raw == "":
        return None

    # Accept pt-BR and en-US number formats.
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")

    try:
        return float(raw)
    except ValueError:
        return None


def _tags_with_metadata(base_tags: str, sold_quantity: Any | None = None) -> str:
    tags = [tag.strip() for tag in base_tags.split(",") if tag.strip()]
    sold_value = int(sold_quantity or 0)
    if sold_value > 0:
        tags.append(f"sold:{sold_value}")
    return ",".join(dict.fromkeys(tags))


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _write_env_updates(updates: dict[str, str]) -> None:
    if not ENV_PATH.exists():
        return

    content = ENV_PATH.read_text(encoding="utf-8").splitlines()
    remaining = dict(updates)
    output: list[str] = []

    for line in content:
        replaced = False
        for key, value in list(remaining.items()):
            if line.startswith(f"{key}="):
                output.append(f"{key}={value}")
                remaining.pop(key, None)
                replaced = True
                break
        if not replaced:
            output.append(line)

    for key, value in remaining.items():
        output.append(f"{key}={value}")

    ENV_PATH.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8")
    for key, value in updates.items():
        os.environ[key] = value


def _refresh_access_token_if_needed() -> str:
    access_token = os.getenv("MELI_ACCESS_TOKEN", "").strip()
    refresh_token = os.getenv("MELI_REFRESH_TOKEN", "").strip()
    if not refresh_token:
        return access_token

    if not access_token:
        tokens = oauth_refresh_token(refresh_token)
        _write_env_updates(
            {
                "MELI_ACCESS_TOKEN": tokens.get("access_token", ""),
                "MELI_REFRESH_TOKEN": tokens.get("refresh_token", refresh_token),
            }
        )
        return os.getenv("MELI_ACCESS_TOKEN", "").strip()

    with httpx.Client(timeout=20) as client:
        resp = client.get(
            f"{MELI_API_URL}/users/me",
            headers=_build_auth_headers(access_token),
        )
        if resp.status_code != 401:
            return access_token

    tokens = oauth_refresh_token(refresh_token)
    _write_env_updates(
        {
            "MELI_ACCESS_TOKEN": tokens.get("access_token", ""),
            "MELI_REFRESH_TOKEN": tokens.get("refresh_token", refresh_token),
        }
    )
    return os.getenv("MELI_ACCESS_TOKEN", "").strip()


def _discount_percent(price: Any, old_price: Any) -> int:
    price_value = _safe_float(price)
    old_price_value = _safe_float(old_price)
    if price_value <= 0 or old_price_value <= price_value:
        return 0
    return int(round(((old_price_value - price_value) / old_price_value) * 100))


def _rank_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    min_price = _safe_float(os.getenv("MELI_MIN_PRICE"), 0.0)
    max_price = _safe_float(os.getenv("MELI_MAX_PRICE"), 0.0)
    min_sold = _safe_int(os.getenv("MELI_MIN_SOLD", "0"), 0)
    max_results = max(1, _safe_int(os.getenv("MELI_MAX_RESULTS", "120"), 120))
    sort_mode = os.getenv("MELI_SORT_MODE", "sales_low_price").strip().lower()

    filtered: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for offer in offers:
        url = (offer.get("url") or "").strip()
        price = _safe_float(offer.get("price"), 0.0)
        sold_quantity = _safe_int(offer.get("sold_quantity"), 0)

        if not url or url in seen_urls or price <= 0:
            continue
        if min_price and price < min_price:
            continue
        if max_price and price > max_price:
            continue
        if sold_quantity < min_sold:
            continue

        seen_urls.add(url)
        filtered.append(offer)

    def sort_key(offer: dict[str, Any]) -> tuple[Any, ...]:
        sold_quantity = _safe_int(offer.get("sold_quantity"), 0)
        price = _safe_float(offer.get("price"), 0.0)
        featured = _safe_int(offer.get("featured"), 0)
        discount = _discount_percent(offer.get("price"), offer.get("old_price"))

        if sort_mode == "low_price_sales":
            return (price, -sold_quantity, -discount, -featured)
        if sort_mode == "discount_sales":
            return (-discount, -sold_quantity, price, -featured)
        return (-sold_quantity, price, -discount, -featured)

    filtered.sort(key=sort_key)
    return filtered[:max_results]


def _fetch_csv_offers() -> list[dict[str, Any]]:
    csv_path = os.getenv("MELI_CSV_PATH", "").strip()
    if not csv_path:
        return []

    path = Path(csv_path)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[2] / csv_path
    if not path.exists():
        return []

    affiliate_tag = os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "")
    offers: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = (row.get("title") or row.get("titulo") or "").strip()
            url = (row.get("url") or row.get("permalink") or row.get("url_produto") or "").strip()
            if not title or not url:
                continue

            price = _parse_float(row.get("price") or row.get("preco")) or 0.0
            old_price = _parse_float(row.get("old_price") or row.get("preco_antigo"))

            featured_raw = (row.get("featured") or row.get("destaque") or "0").strip().lower()
            featured = 1 if featured_raw in {"1", "true", "sim", "yes"} else 0

            offers.append(
                {
                    "title": title,
                    "description": (row.get("description") or row.get("descricao") or "").strip(),
                    "price": price,
                    "old_price": old_price,
                    "url": url,
                    "image": (row.get("image") or row.get("imagem_url") or "").strip(),
                    "category": (row.get("category") or row.get("categoria") or "ofertas").strip(),
                    "tags": _tags_with_metadata((row.get("tags") or "").strip() or "mercadolivre,csv", row.get("sold_quantity") or row.get("vendidos")),
                    "featured": featured,
                    "coupon": (row.get("coupon") or row.get("cupom") or "").strip() or None,
                    "item_id": (row.get("item_id") or row.get("wid") or "").strip() or None,
                    "product_id": (row.get("product_id") or row.get("catalog_product_id") or "").strip() or None,
                    "affiliate_tag": affiliate_tag,
                }
            )

    return offers


def _fetch_public_search_offers(client: httpx.Client) -> list[dict[str, Any]]:
    site = os.getenv("MELI_SITE", "MLB")
    terms = _env_list("MELI_QUERY_TERMS", "fone bluetooth,air fryer,notebook")
    limit = int(os.getenv("MELI_LIMIT_PER_QUERY", "15"))
    pages = max(1, int(os.getenv("MELI_PAGES_PER_QUERY", "3")))
    affiliate_tag = os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "")

    offers: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for term in terms:
        term_offers: list[dict[str, Any]] = []
        for page in range(pages):
            try:
                resp = client.get(
                    f"{MELI_API_URL}/sites/{site}/search",
                    params={"q": term, "limit": limit, "offset": page * limit},
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError:
                # Some accounts/contexts are blocked by policy in public search.
                # Keep flow resilient and continue with next query term.
                break
            data = resp.json()

            for item in data.get("results", []):
                item_url = item.get("permalink", "#")
                if item_url in seen_urls:
                    continue
                seen_urls.add(item_url)
                term_offers.append(
                    {
                        "title": item.get("title", "Oferta Mercado Livre"),
                        "description": f"Oferta automatica para: {term}",
                        "price": float(item.get("price") or 0),
                        "old_price": float(item.get("original_price")) if item.get("original_price") else None,
                        "url": item_url,
                        "image": item.get("thumbnail", ""),
                        "category": str(item.get("category_id") or "ofertas"),
                        "tags": _tags_with_metadata(f"mercadolivre,{term}", item.get("sold_quantity")),
                        "featured": 0,
                        "sold_quantity": int(item.get("sold_quantity") or 0),
                        "item_id": item.get("id"),
                        "product_id": item.get("catalog_product_id"),
                        "affiliate_tag": affiliate_tag,
                    }
                )

        term_offers.sort(key=lambda offer: offer.get("sold_quantity", 0), reverse=True)
        offers.extend(term_offers)

    return offers


def preview_mercadolivre_offers(keyword: str, limit: int = 10, pages: int = 1) -> list[dict[str, Any]]:
    site = os.getenv("MELI_SITE", "MLB")
    affiliate_tag = os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "")
    offers: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    with httpx.Client(timeout=20) as client:
        for page in range(max(1, pages)):
            resp = client.get(
                f"{MELI_API_URL}/sites/{site}/search",
                params={"q": keyword, "limit": limit, "offset": page * limit},
            )
            resp.raise_for_status()
            data = resp.json()

            for item in data.get("results", []):
                item_url = item.get("permalink", "#")
                if item_url in seen_urls:
                    continue
                seen_urls.add(item_url)
                offers.append(
                    {
                        "title": item.get("title", "Oferta Mercado Livre"),
                        "description": f"Oferta automatica para: {keyword}",
                        "price": float(item.get("price") or 0),
                        "old_price": float(item.get("original_price")) if item.get("original_price") else None,
                        "url": item_url,
                        "image": item.get("thumbnail", ""),
                        "category": str(item.get("category_id") or "ofertas"),
                        "tags": _tags_with_metadata(f"mercadolivre,{keyword}", item.get("sold_quantity")),
                        "featured": 0,
                        "sold_quantity": int(item.get("sold_quantity") or 0),
                        "item_id": item.get("id"),
                        "product_id": item.get("catalog_product_id"),
                        "affiliate_tag": affiliate_tag,
                    }
                )

    return _rank_offers(offers)


def _fetch_authorized_seller_offers(client: httpx.Client, access_token: str) -> list[dict[str, Any]]:
    headers = _build_auth_headers(access_token)
    affiliate_tag = os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "")
    limit = int(os.getenv("MELI_LIMIT_PER_QUERY", "20"))

    me = client.get(f"{MELI_API_URL}/users/me", headers=headers)
    me.raise_for_status()
    user_id = me.json().get("id")
    if not user_id:
        return []

    items_resp = client.get(
        f"{MELI_API_URL}/users/{user_id}/items/search",
        headers=headers,
        params={"status": "active", "limit": limit},
    )
    items_resp.raise_for_status()
    results = items_resp.json().get("results", [])
    if not results:
        return []

    ids_csv = ",".join(results)
    details_resp = client.get(
        f"{MELI_API_URL}/items",
        headers=headers,
        params={"ids": ids_csv},
    )
    details_resp.raise_for_status()
    details = details_resp.json()

    offers: list[dict[str, Any]] = []
    for wrapped in details:
        item = wrapped.get("body", {}) if isinstance(wrapped, dict) else {}
        offers.append(
            {
                "title": item.get("title", "Oferta Mercado Livre"),
                "description": "Oferta importada por API autenticada do Mercado Livre",
                "price": float(item.get("price") or 0),
                "old_price": float(item.get("original_price")) if item.get("original_price") else None,
                "url": item.get("permalink", "#"),
                "image": item.get("thumbnail", ""),
                "category": str(item.get("category_id") or "ofertas"),
                "tags": _tags_with_metadata("mercadolivre,auth", item.get("sold_quantity")),
                "featured": 0,
                "sold_quantity": int(item.get("sold_quantity") or 0),
                "item_id": item.get("id"),
                "product_id": item.get("catalog_product_id"),
                "affiliate_tag": affiliate_tag,
            }
        )

    offers.sort(key=lambda offer: offer.get("sold_quantity", 0), reverse=True)
    return offers


def _fetch_highlight_offers(client: httpx.Client, access_token: str) -> list[dict[str, Any]]:
    headers = _build_auth_headers(access_token)
    affiliate_tag = os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "")
    categories = _env_list("MELI_HIGHLIGHT_CATEGORIES", "MLB1055")
    limit_per_category = max(1, _safe_int(os.getenv("MELI_HIGHLIGHT_LIMIT", "24"), 24))

    offers: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for category_id in categories:
        highlight_resp = client.get(
            f"{MELI_API_URL}/highlights/MLB/category/{category_id}",
            headers=headers,
        )
        highlight_resp.raise_for_status()
        content = highlight_resp.json().get("content", [])

        product_ids = [
            item.get("id")
            for item in content
            if isinstance(item, dict) and item.get("id")
        ][:limit_per_category]

        for product_id in product_ids:
            try:
                product_resp = client.get(
                    f"{MELI_API_URL}/products/{product_id}",
                    headers=headers,
                )
                product_resp.raise_for_status()
                product = product_resp.json()

                items_resp = client.get(
                    f"{MELI_API_URL}/products/{product_id}/items",
                    headers=headers,
                    params={"limit": 1},
                )
                items_resp.raise_for_status()
                results = items_resp.json().get("results", [])
            except httpx.HTTPStatusError:
                continue

            if not results:
                continue
            item = results[0]

            item_url = product.get("permalink") or f"https://www.mercadolivre.com.br/p/{product_id}"
            if item_url in seen_urls:
                continue
            seen_urls.add(item_url)

            image = ""
            pictures = product.get("pictures") or []
            if pictures:
                image = pictures[0].get("url", "")
            if not image:
                for picker in product.get("pickers", []):
                    picker_products = picker.get("products") or []
                    if picker_products:
                        image = picker_products[0].get("thumbnail", "")
                        if image:
                            break

            title = (
                product.get("name")
                or product.get("family_name")
                or "Oferta Mercado Livre"
            )

            offers.append(
                {
                    "title": title,
                    "description": f"Produto mais vendido na categoria {category_id}",
                    "price": float(item.get("price") or 0),
                    "old_price": float(item.get("original_price")) if item.get("original_price") else None,
                    "url": item_url,
                    "image": image,
                    "category": str(item.get("category_id") or category_id or "ofertas"),
                    "tags": _tags_with_metadata(f"mercadolivre,highlight,{category_id}"),
                    "featured": 1,
                    "sold_quantity": 0,
                    "coupon": None,
                    "item_id": item.get("item_id"),
                    "product_id": product_id,
                    "affiliate_tag": affiliate_tag,
                }
            )

    offers.sort(key=lambda offer: offer.get("sold_quantity", 0), reverse=True)
    return offers


def fetch_mercadolivre_offers() -> list[dict[str, Any]]:
    # Priority mode: local CSV feed for fast bootstrap.
    csv_offers = _fetch_csv_offers()
    if csv_offers:
        return csv_offers

    access_token = _refresh_access_token_if_needed()

    with httpx.Client(timeout=20) as client:
        if access_token:
            try:
                offers: list[dict[str, Any]] = []
                offers.extend(_fetch_authorized_seller_offers(client, access_token))
                offers.extend(_fetch_highlight_offers(client, access_token))
                offers.extend(_fetch_public_search_offers(client))
                return _rank_offers(offers)
            except httpx.HTTPStatusError:
                try:
                    offers = _fetch_highlight_offers(client, access_token)
                    offers.extend(_fetch_public_search_offers(client))
                    return _rank_offers(offers)
                except Exception:
                    return _rank_offers(_fetch_public_search_offers(client))
            except Exception:
                return []

        try:
            return _rank_offers(_fetch_public_search_offers(client))
        except Exception:
            return []
