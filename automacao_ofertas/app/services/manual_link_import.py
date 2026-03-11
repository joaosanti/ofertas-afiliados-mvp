import re
import time
from collections import Counter
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from app.collectors.shopee import preview_shopee_affiliate_links
from app.services.category_inference import infer_category_label


PROVIDER_LABELS = {
    "mercadolivre": "Mercado Livre",
    "shopee": "Shopee",
    "amazon": "Amazon",
    "tiktok": "TikTok",
}


def _meli_affiliate_meta(url: str) -> dict[str, Any]:
    parsed = urlparse(url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    combined = {**query, **fragment}

    wid = (combined.get("wid") or [None])[0]
    sid = (combined.get("sid") or [None])[0]
    polycard_client = (combined.get("polycard_client") or [None])[0]
    matt_tool = (combined.get("matt_tool") or [None])[0]
    source = (combined.get("source") or [None])[0]
    reco_client = (combined.get("reco_client") or [None])[0]
    is_social = "/social/" in (parsed.path or "").lower()

    official = bool(
        matt_tool
        or is_social
        or (wid and sid == "affiliates")
        or (wid and polycard_client == "affiliates")
        or (wid and sid == "recos" and source == "affiliate-profile")
        or (wid and source == "affiliate-profile")
        or (wid and reco_client == "home_affiliate-profile")
        or (wid and isinstance(polycard_client, str) and "affiliate-profile" in polycard_client)
    )
    code = matt_tool or wid

    warning = None
    if not official:
        warning = (
            "Link do Mercado Livre sem marcador oficial de afiliado. "
            "Gere o link na Central/Barra de Afiliados antes de importar."
        )

    return {
        "official": official,
        "code": code,
        "warning": warning,
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
        parsed = urlparse(raw)
        host = (parsed.netloc or "").lower()
        if host in {"l.facebook.com", "lm.facebook.com"}:
            target = (parse_qs(parsed.query, keep_blank_values=True).get("u") or [raw])[0]
            return unquote(target).strip() or raw
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


def _extract_ml_title_from_url(url: str) -> str:
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


def _extract_ml_product_id_from_url(url: str) -> str | None:
    match = re.search(r"/p/(MLB\d+)", (url or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _build_ml_fallback_offer(link: str) -> dict[str, Any]:
    meta = _meli_affiliate_meta(link)
    title = _extract_ml_title_from_url(link)
    description = (
        "Oferta Mercado Livre importada por link oficial. "
        "A pagina bloqueou a leitura automatica, entao revise preco, imagem e descricao antes de importar."
    )
    return {
        "provider": "mercadolivre",
        "store": "Mercado Livre",
        "title": title,
        "description": description,
        "price": 0.0,
        "old_price": None,
        "url": link,
        "canonical_url": link,
        "image": "",
        "category": infer_category_label(title, description, link, link, default="ofertas"),
        "tags": "mercadolivre,manual,fallback",
        "featured": 0,
        "affiliate_detected": bool(meta["official"]),
        "affiliate_code": meta["code"],
        "affiliate_status": "official" if meta["official"] else "missing",
        "affiliate_warning": (
            "Link oficial detectado, mas o Mercado Livre bloqueou a leitura automatica. Revise os dados antes de importar."
            if meta["official"]
            else meta["warning"]
        ),
        "import_allowed": bool(meta["official"]),
        "item_id": meta["code"] if str(meta["code"] or "").upper().startswith("MLB") else None,
        "product_id": _extract_ml_product_id_from_url(link),
    }


def _extract_amazon_asin_from_url(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", (url or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _extract_amazon_title_from_url(url: str) -> str:
    path = unquote(urlparse(url).path or "")
    match = re.search(r"/([^/]+)/dp/[A-Z0-9]{10}", path, re.IGNORECASE)
    if match:
        text = re.sub(r"[-_]+", " ", match.group(1)).strip()
        if text:
            return text[:180]
    asin = _extract_amazon_asin_from_url(url)
    return f"Oferta Amazon {asin}" if asin else "Oferta Amazon"


def _build_amazon_fallback_offer(link: str) -> dict[str, Any]:
    parsed = urlparse(link)
    host = (parsed.netloc or "").lower()
    affiliate_detected, affiliate_code = _detect_affiliate(link)
    is_short = host == "amzn.to"
    title = _extract_amazon_title_from_url(link)
    description = (
        "Oferta Amazon importada por link manual. "
        "A pagina bloqueou a leitura automatica, entao revise preco, imagem e descricao antes de importar."
    )
    warning = (
        "Shortlink Amazon aceito. Revise os dados do produto antes de importar."
        if is_short
        else "Link Amazon com afiliado detectado, mas a pagina bloqueou a leitura automatica. Revise os dados antes de importar."
    )
    return {
        "provider": "amazon",
        "store": "Amazon",
        "title": title,
        "description": description,
        "price": 0.0,
        "old_price": None,
        "url": link,
        "canonical_url": link,
        "image": "",
        "category": infer_category_label(title, description, link, link, default="ofertas"),
        "tags": "amazon,manual,fallback",
        "featured": 0,
        "affiliate_detected": bool(affiliate_detected or is_short),
        "affiliate_code": affiliate_code,
        "affiliate_status": "official" if (affiliate_detected or is_short) else "missing",
        "affiliate_warning": warning,
        "import_allowed": bool(affiliate_detected or is_short),
        "item_id": None,
        "product_id": _extract_amazon_asin_from_url(link),
    }


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
        meta = _meli_affiliate_meta(url)
        return (bool(meta["official"]), meta["code"])
    if "amazon." in host or "amzn.to" in host:
        if "amzn.to" in host:
            return (True, None)
        code = (combined.get("tag") or [None])[0]
        return (code is not None, code)
    if "tiktok" in host:
        code = (combined.get("pid") or combined.get("affiliate_id") or combined.get("aid") or [None])[0]
        serialized = parsed.query.lower()
        return ("aff" in serialized or code is not None, code)
    return False, None


def _extract_generic_offer(provider: str, source_url: str, final_url: str, html_text: str) -> dict[str, Any]:
    if provider == "mercadolivre":
        final_lower = (final_url or "").lower()
        html_lower = (html_text or "").lower()
        blocked_markers = (
            "registrationtype=negative_traffic",
            "negative_traffic",
            "account-verification-main",
            "mercadolivre.com/jms/mlb/lgz/login",
            "mercadolivre.com.br/registration",
            "\"error\":\"forbidden\"",
            "\"message\":\"forbidden\"",
        )
        if any(marker in final_lower or marker in html_lower for marker in blocked_markers):
            raise ValueError("Mercado Livre bloqueou temporariamente a leitura desta pagina/link. Tente novamente mais tarde.")

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
    if provider == "mercadolivre":
        normalized_title = (title or "").strip().lower()
        if normalized_title in {"mercado livre", "mercadolivre"} or price <= 0:
            raise ValueError("Mercado Livre nao retornou os dados do produto. Isso normalmente acontece quando a pagina foi bloqueada temporariamente.")
    affiliate_detected, affiliate_code = _detect_affiliate(final_url or source_url)
    import_allowed = True
    affiliate_warning = None
    affiliate_status = "ok" if affiliate_detected else "missing"
    if provider == "mercadolivre":
        meta = _meli_affiliate_meta(source_url)
        affiliate_detected = bool(meta["official"])
        affiliate_code = meta["code"]
        affiliate_warning = meta["warning"]
        import_allowed = affiliate_detected
        affiliate_status = "official" if affiliate_detected else "missing"

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
        "affiliate_status": affiliate_status,
        "affiliate_warning": affiliate_warning,
        "import_allowed": import_allowed,
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
    attempts = 2 if provider == "mercadolivre" else 1
    for attempt in range(attempts):
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
        if provider == "mercadolivre" and attempt + 1 < attempts:
            time.sleep(2)
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

        try:
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
        except Exception:
            if provider == "mercadolivre" and _meli_affiliate_meta(link)["official"]:
                items.append(_build_ml_fallback_offer(link))
                continue
            if provider == "amazon":
                affiliate_detected, _ = _detect_affiliate(link)
                if affiliate_detected:
                    items.append(_build_amazon_fallback_offer(link))
                    continue
            raise

    return items
