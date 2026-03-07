import hashlib
import json
import os
import time
from typing import Any

import httpx


SHOPEE_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"
DEFAULT_QUERY = """
query ProductOfferQuery($keyword: String!, $limit: Int!, $page: Int!, $sortType: Int!) {
  productOfferV2(keyword: $keyword, limit: $limit, page: $page, sortType: $sortType) {
    nodes {
      productId
      productName
      productLink
      offerLink
      imageUrl
      commissionRate
      priceMin
      priceMax
      sales
      shopId
      shopName
      ratingStar
    }
    pageInfo {
      page
      limit
    }
  }
}
""".strip()


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None

    raw = str(value).strip()
    if not raw:
        return None

    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")

    try:
        return float(raw)
    except ValueError:
        return None


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_price(value: Any) -> float:
    parsed = _safe_float(value)
    if parsed is None:
        return 0.0

    divisor = max(1, _safe_int(os.getenv("SHOPEE_PRICE_DIVISOR", "100000"), 100000))
    return round(parsed / divisor, 2) if parsed >= divisor else round(parsed, 2)


def _build_auth_headers(credential: str, secret: str, payload: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    base_string = f"{credential}{timestamp}{payload}{secret}"
    signature = hashlib.sha256(base_string.encode("utf-8")).hexdigest()
    authorization = f"SHA256 Credential={credential}, Timestamp={timestamp}, Signature={signature}"

    return {
        "Authorization": authorization,
        "Content-Type": "application/json",
    }


def _iter_feed_items(data: Any) -> list[dict[str, Any]]:
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        if isinstance(data.get("items"), list):
            return data["items"]
        if isinstance(data.get("data"), list):
            return data["data"]

    return []


def _fetch_feed_offers() -> list[dict[str, Any]]:
    feed_url = os.getenv("SHOPEE_FEED_URL", "").strip()
    affiliate_tag = os.getenv("SHOPEE_AFFILIATE_TAG", "").strip()

    if not feed_url:
        return []

    with httpx.Client(timeout=20) as client:
        resp = client.get(feed_url)
        resp.raise_for_status()
        data = resp.json()

    offers: list[dict[str, Any]] = []
    for item in _iter_feed_items(data):
        offers.append(
            {
                "title": item.get("title", "Oferta Shopee"),
                "description": item.get("description", ""),
                "price": float(item.get("price") or 0),
                "old_price": float(item.get("old_price")) if item.get("old_price") else None,
                "url": item.get("url", "#"),
                "image": item.get("image", ""),
                "category": item.get("category", "ofertas"),
                "tags": item.get("tags", "shopee"),
                "featured": int(item.get("featured", 0)),
                "affiliate_tag": affiliate_tag,
            }
        )

    return offers


def _build_graphql_query() -> str:
    return os.getenv("SHOPEE_GRAPHQL_QUERY", "").strip() or DEFAULT_QUERY


def _build_graphql_variables(keyword: str, page: int, limit: int, sort_type: int) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "page": page,
        "limit": limit,
        "sortType": sort_type,
    }


def _extract_nodes(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data", {})
    product_offer = payload.get("productOfferV2") or payload.get("productOffer") or {}
    nodes = product_offer.get("nodes") or product_offer.get("items") or []
    return nodes if isinstance(nodes, list) else []


def _node_to_offer(node: dict[str, Any], keyword: str, affiliate_tag: str) -> dict[str, Any]:
    price_min = node.get("priceMin") or node.get("price") or node.get("minPrice")
    price_max = node.get("priceMax") or node.get("maxPrice")
    price = _normalize_price(price_min)
    old_price = _normalize_price(price_max) if price_max else None
    commission_rate = _safe_float(node.get("commissionRate"))
    shop_name = (node.get("shopName") or "").strip()
    sales = _safe_int(node.get("sales"))

    tags = ["shopee", keyword]
    if shop_name:
        tags.append(shop_name.lower().replace(" ", "-"))
    if commission_rate is not None:
        tags.append(f"commission:{commission_rate}")
    if sales > 0:
        tags.append(f"sold:{sales}")

    return {
        "title": node.get("productName") or node.get("title") or "Oferta Shopee",
        "description": f"Oferta Shopee encontrada para: {keyword}",
        "price": price,
        "old_price": old_price if old_price and old_price > price else None,
        "url": node.get("offerLink") or node.get("productLink") or "#",
        "image": node.get("imageUrl") or node.get("image") or "",
        "category": "ofertas",
        "tags": ",".join(dict.fromkeys(tags)),
        "featured": 0,
        "affiliate_tag": affiliate_tag,
        "product_id": str(node.get("productId") or "") or None,
        "shop_id": str(node.get("shopId") or "") or None,
        "sales": sales,
        "commission_rate": commission_rate,
    }


def _fetch_api_offers(keyword_override: str | None = None, page_override: int | None = None, limit_override: int | None = None) -> list[dict[str, Any]]:
    credential = (
        os.getenv("SHOPEE_API_KEY", "").strip()
        or os.getenv("SHOPEE_APP_ID", "").strip()
        or os.getenv("SHOPEE_PARTNER_ID", "").strip()
    )
    secret = os.getenv("SHOPEE_API_SECRET", "").strip() or os.getenv("SHOPEE_SECRET_KEY", "").strip()
    affiliate_tag = os.getenv("SHOPEE_AFFILIATE_TAG", "").strip()
    api_url = os.getenv("SHOPEE_API_URL", SHOPEE_API_URL).strip() or SHOPEE_API_URL

    if not credential or not secret:
        return []

    keywords_raw = keyword_override or os.getenv(
        "SHOPEE_QUERY_TERMS",
        "fone bluetooth,air fryer,notebook,smart tv,iphone,samsung",
    )
    keywords = [item.strip() for item in keywords_raw.split(",") if item.strip()]
    if not keywords:
        return []

    limit = max(1, limit_override or _safe_int(os.getenv("SHOPEE_LIMIT_PER_QUERY", "20"), 20))
    pages = max(1, page_override or _safe_int(os.getenv("SHOPEE_PAGES_PER_QUERY", "2"), 2))
    sort_type = _safe_int(os.getenv("SHOPEE_SORT_TYPE", "1"), 1)
    timeout = max(5, _safe_int(os.getenv("SHOPEE_TIMEOUT", "20"), 20))
    query = _build_graphql_query()

    offers: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    with httpx.Client(timeout=timeout) as client:
        for keyword in keywords:
            for page in range(1, pages + 1):
                variables = _build_graphql_variables(keyword, page, limit, sort_type)
                body = {"query": query, "variables": variables}
                payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
                headers = _build_auth_headers(credential, secret, payload)

                response = client.post(api_url, content=payload.encode("utf-8"), headers=headers)
                response.raise_for_status()
                data = response.json()

                for error in data.get("errors", []) or []:
                    message = error.get("message") if isinstance(error, dict) else str(error)
                    raise ValueError(f"Shopee GraphQL error: {message}")

                nodes = _extract_nodes(data)
                if not nodes:
                    break

                for node in nodes:
                    offer = _node_to_offer(node, keyword, affiliate_tag)
                    url = offer.get("url", "#")
                    if not url or url == "#" or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    offers.append(offer)

    offers.sort(
        key=lambda offer: (
            _safe_int(offer.get("sales"), 0),
            _safe_float(offer.get("commission_rate")) or 0.0,
        ),
        reverse=True,
    )
    return offers


def fetch_shopee_offers() -> list[dict[str, Any]]:
    api_offers = _fetch_api_offers()
    if api_offers:
        return api_offers
    return _fetch_feed_offers()


def preview_shopee_offers(keyword: str, limit: int = 10, pages: int = 1) -> list[dict[str, Any]]:
    return _fetch_api_offers(keyword_override=keyword, limit_override=limit, page_override=pages)
