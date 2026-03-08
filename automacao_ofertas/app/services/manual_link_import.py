import re
from collections import Counter
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx

from app.collectors.shopee import preview_shopee_affiliate_links
from app.services.category_inference import infer_category_label


PROVIDER_LABELS = {
    "mercadolivre": "Mercado Livre",
    "shopee": "Shopee",
    "amazon": "Amazon",
    "tiktok": "TikTok",
}


def _extract_first(content: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return unescape((match.group(1) or "").strip())
    return ""


def _extract_all(content: str, patterns: list[str]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        matches = re.findall(pattern, content, re.IGNORECASE | re.DOTALL)
        for match in matches:
            if isinstance(match, tuple):
                value = "".join(str(part or "") for part in match)
            else:
                value = str(match or "")
            value = unescape(value.strip())
            if value:
                values.append(value)
    return values


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


def _normalize_price(value: Any) -> float:
    parsed = _safe_float(value)
    return round(parsed or 0.0, 2)


def _normalize_link(link: str) -> str:
    raw = (link or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw.lstrip('/')}"


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }


def _crawler_headers() -> dict[str, str]:
    return {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }


def _looks_like_html(body: str) -> bool:
    sample = (body or "").lstrip().lower()
    return sample.startswith("<!doctype html") or sample.startswith("<html") or "<head" in sample[:500]


def detect_provider(url: str) -> str:
    host = (urlparse(url).netloc or "").lower()
    if "mercadolivre" in host or "mercadolibre" in host:
        return "mercadolivre"
    if "shopee" in host:
        return "shopee"
    if "amazon." in host or "amzn.to" in host:
        return "amazon"
    if "tiktok" in host:
        return "tiktok"
    raise ValueError(f"Dominio ainda nao suportado para importacao manual: {host or url}")


def _provider_label(provider: str) -> str:
    return PROVIDER_LABELS.get(provider, provider.title())


def _clean_title(title: str, provider: str) -> str:
    patterns = {
        "mercadolivre": r"\s*\|\s*Mercado Livre\s*$",
        "shopee": r"\s*\|\s*Shopee Brasil\s*$",
        "amazon": r"\s*\|\s*Amazon(?:\.com\.br)?\s*$",
        "tiktok": r"\s*\|\s*TikTok Shop\s*$",
    }
    pattern = patterns.get(provider)
    if pattern:
        title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
    if provider == "amazon":
        title = re.sub(r"^\s*Oferta:\s*", "", title, flags=re.IGNORECASE).strip()
    return title.strip()


def _detect_affiliate(url: str) -> tuple[bool, str | None]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    combined = {**query, **fragment}
    host = (parsed.netloc or "").lower()

    if "shopee" in host:
        code = (combined.get("mmp_pid") or combined.get("utm_source") or [None])[0]
        return (
            (combined.get("utm_medium") or [""])[0] == "affiliates" or bool(code and str(code).startswith("an_")),
            code,
        )
    if "mercadolivre" in host or "mercadolibre" in host:
        code = (combined.get("wid") or combined.get("matt_tool") or [None])[0]
        return ("affiliates" in parsed.fragment.lower() or code is not None, code)
    if "amazon." in host or "amzn.to" in host:
        code = (combined.get("tag") or [None])[0]
        return (code is not None, code)
    if "tiktok" in host:
        code = (combined.get("pid") or combined.get("affiliate_id") or combined.get("aid") or [None])[0]
        serialized = parsed.query.lower()
        return ("aff" in serialized or code is not None, code)
    return False, None


def _extract_generic_offer(provider: str, source_url: str, final_url: str, html_text: str) -> dict[str, Any]:
    title = _extract_first(
        html_text,
        [
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<title>(.*?)</title>',
        ],
    )
    title = _clean_title(title, provider)
    if not title:
        raise ValueError(f"Nao foi possivel extrair o titulo do link de {_provider_label(provider)}.")

    image = _extract_first(
        html_text,
        [
            r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        ],
    )
    if not image and provider == "amazon":
        image = _extract_first(
            html_text,
            [
                r'"hiRes":"([^"]+)"',
                r'"large":"([^"]+)"',
                r'id=["\']landingImage["\'][^>]+src=["\']([^"\']+)["\']',
                r'id=["\']imgTagWrapperId["\'][\s\S]{0,800}?<img[^>]+src=["\']([^"\']+)["\']',
            ],
        )
        image = image.replace("\\u0026", "&").replace("\\/", "/")
    description = _extract_first(
        html_text,
        [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']+)["\']',
        ],
    )

    price_patterns = {
        "mercadolivre": [
            r'itemprop=["\']price["\'][^>]+content=["\']([\d\.,]+)["\']',
            r'property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']',
            r'"price"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'por\s+R\$\s*([\d\.,]+)',
        ],
        "amazon": [
            r'priceToPay[^>]*a-offscreen[^>]*>\s*R\$\s*([\d\.,]+)',
            r'a-offscreen">\s*R\$\s*([\d\.,]+)',
            r'id=["\']attach-base-product-price["\']\s+value=["\']([\d\.,]+)["\']',
            r'"priceAmount"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']',
        ],
        "tiktok": [
            r'"price"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']',
        ],
    }
    old_price_patterns = {
        "mercadolivre": [
            r'"originalPrice"\s*:\s*"?(\\?[\d\.,]+)"?',
        ],
        "amazon": [
            r'"listPriceAmount"\s*:\s*"?(\\?[\d\.,]+)"?',
        ],
        "tiktok": [
            r'"original_price"\s*:\s*"?(\\?[\d\.,]+)"?',
        ],
    }

    price_raw = ""
    if provider == "amazon":
        pair_match = re.search(
            r'a-price-whole">\s*([\d\.,]+).*?a-price-fraction">\s*([\d]{2})',
            html_text,
            re.IGNORECASE | re.DOTALL,
        )
        if pair_match:
            price_raw = f"{pair_match.group(1)},{pair_match.group(2)}"
    if not price_raw:
        price_raw = _extract_first(html_text, price_patterns.get(provider, []))
    price = _normalize_price(price_raw)
    old_price = _normalize_price(_extract_first(html_text, old_price_patterns.get(provider, [])))
    if provider in {"amazon", "mercadolivre", "tiktok"}:
        visible_price_patterns = [
            r'R\$\s*([\d\.,]+)',
            r'"price"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'"priceAmount"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']',
        ]
        if provider == "amazon":
            visible_price_patterns = [
                r'a-offscreen">\s*R\$\s*([\d\.,]+)',
                r'a-price-whole">\s*([\d\.,]+).*?a-price-fraction">\s*([\d]{2})',
                r'id=["\']attach-base-product-price["\']\s+value=["\']([\d\.,]+)["\']',
            ]
        visible_prices = []
        for value in _extract_all(html_text, visible_price_patterns):
            normalized = _normalize_price(value)
            if normalized > 0:
                visible_prices.append(normalized)
        visible_price_counts = Counter(visible_prices)
        visible_prices = list(dict.fromkeys(visible_prices))
        if visible_prices:
            if price <= 0:
                if provider == "amazon":
                    meaningful = [value for value in visible_prices if value >= 10]
                    if meaningful:
                        price = meaningful[0]
                        if price < 10 or visible_price_counts[price] == 1:
                            price = max(meaningful, key=lambda value: (visible_price_counts[value], -meaningful.index(value)))
                    else:
                        price = visible_prices[0]
                else:
                    price = visible_prices[0]
            if old_price is None:
                higher_prices = [value for value in visible_prices if value > price]
                if higher_prices:
                    old_price = higher_prices[0]
    affiliate_detected, affiliate_code = _detect_affiliate(final_url or source_url)

    return {
        "provider": provider,
        "store": _provider_label(provider),
        "title": title,
        "description": description or f"Oferta {_provider_label(provider)} importada manualmente.",
        "price": price,
        "old_price": old_price if old_price > price > 0 else None,
        "url": source_url,
        "canonical_url": final_url,
        "image": image,
        "category": infer_category_label(title, description, source_url, final_url),
        "tags": f"{provider},manual",
        "featured": 0,
        "affiliate_detected": affiliate_detected,
        "affiliate_code": affiliate_code,
    }


def _fetch_html_with_fallback(link: str) -> tuple[str, str]:
    last_error: Exception | None = None
    for headers in (_browser_headers(), _crawler_headers()):
        try:
            with httpx.Client(timeout=25, headers=headers, follow_redirects=True) as client:
                response = client.get(link)
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type and not _looks_like_html(response.text):
                    raise ValueError("O link retornou um formato inesperado.")
                return str(response.url), response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("Falha ao abrir o link informado.")


def _fetch_best_html_for_provider(link: str, provider: str) -> tuple[str, str]:
    headers_order = (_crawler_headers(), _browser_headers()) if provider in {"amazon", "shopee"} else (_browser_headers(), _crawler_headers())
    last_error: Exception | None = None
    for headers in headers_order:
        try:
            with httpx.Client(timeout=25, headers=headers, follow_redirects=True) as client:
                response = client.get(link)
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if "text/html" not in content_type and "application/xhtml" not in content_type and not _looks_like_html(response.text):
                    raise ValueError("O link retornou um formato inesperado.")
                return str(response.url), response.text
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("Falha ao abrir o link informado.")


def preview_manual_affiliate_links(links: list[str]) -> list[dict[str, Any]]:
    cleaned_links = [item for item in (_normalize_link(link) for link in links) if item]
    if not cleaned_links:
        raise ValueError("Cole pelo menos um link para analisar.")

    items: list[dict[str, Any]] = []
    for link in cleaned_links:
        provider = detect_provider(link)
        if provider == "shopee":
            shopee_items = preview_shopee_affiliate_links([link])
            for item in shopee_items:
                affiliate_detected, affiliate_code = _detect_affiliate(item.get("url") or link)
                items.append(
                    {
                        "provider": "shopee",
                        "store": "Shopee",
                        "title": item.get("title") or "Oferta Shopee",
                        "description": item.get("description") or "Oferta Shopee importada manualmente.",
                        "price": float(item.get("price") or 0),
                        "old_price": float(item["old_price"]) if item.get("old_price") else None,
                        "url": item.get("url") or link,
                        "canonical_url": item.get("canonical_url") or link,
                        "image": item.get("image") or "",
                        "category": item.get("category") or infer_category_label(item.get("title"), item.get("description"), item.get("url"), item.get("canonical_url")),
                        "tags": item.get("tags") or "shopee,manual",
                        "featured": int(item.get("featured") or 0),
                        "affiliate_detected": affiliate_detected,
                        "affiliate_code": affiliate_code,
                    }
                )
            continue

        final_url, html_text = _fetch_best_html_for_provider(link, provider)
        provider = detect_provider(final_url)
        try:
            items.append(_extract_generic_offer(provider, link, final_url, html_text))
        except ValueError:
            if provider in {"amazon", "shopee"}:
                retry_url, retry_html = _fetch_best_html_for_provider(link, provider)
                items.append(_extract_generic_offer(provider, link, retry_url, retry_html))
            else:
                raise

    return items
