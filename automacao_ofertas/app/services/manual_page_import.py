import os
import re
from html import unescape
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import httpx

from app.collectors.mercadolivre import preview_mercadolivre_offers
from app.services.category_inference import infer_category_label
from app.services.manual_link_import import (
    _browser_headers,
    _clean_title,
    _detect_affiliate,
    _extract_all,
    _extract_first,
    _normalize_price,
    preview_manual_affiliate_links,
)


def _normalize_provider_from_url(url: str) -> str:
    host = (urlparse((url or "").strip()).netloc or "").lower()
    if "mercadolivre.com.br" in host or "mercadolibre.com" in host:
        return "mercadolivre"
    if "amazon." in host or "amzn.to" in host:
        return "amazon"
    raise ValueError("A URL da pagina precisa ser do Mercado Livre ou da Amazon.")


def _clean_ml_title(value: str) -> str:
    title = (value or "").strip()
    title = re.sub(r"\s*-\s*R\$\s*[\d\.,]+\s*$", "", title, flags=re.IGNORECASE).strip()
    return title


def _clean_amazon_url(url: str, tag: str | None) -> str:
    parsed = urlparse((url or "").strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    allowed = []
    for key in ("tag", "linkCode", "linkId", "ref_", "ref"):
        if key in query and query[key]:
            allowed.append((key, query[key][-1]))
    if tag:
        allowed = [(key, value) for key, value in allowed if key != "tag"]
        allowed.append(("tag", tag))
    cleaned_query = urlencode(allowed)
    return urlunparse(parsed._replace(query=cleaned_query, fragment=""))


def _extract_ml_listing_product_links(html_text: str, limit: int) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    patterns = [
        r'https://[^"\']*mercadolivre\.com\.br/[^"\']+',
        r'https:\\/\\/[^"\']*mercadolivre\.com\.br\\/[^"\']+',
    ]
    for pattern in patterns:
        for raw_match in re.findall(pattern, html_text or "", re.IGNORECASE):
            url = str(raw_match or "").replace("\\/", "/").replace("&amp;", "&").strip()
            if not url.startswith("https://"):
                continue
            if ("mercadolivre.com.br/p/" not in url and "/MLB" not in url) or "wid=" not in url:
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= limit:
                return links
    return links


def _extract_amazon_listing_product_links(html_text: str, limit: int, tag: str | None) -> list[str]:
    links: list[str] = []
    seen: set[str] = set()
    patterns = [
        r'https://www\.amazon\.com\.br/[^"\']*/dp/[A-Z0-9]{10}[^"\']*',
        r'https://www\.amazon\.com\.br/dp/[A-Z0-9]{10}[^"\']*',
        r'https://www\.amazon\.com\.br/gp/product/[A-Z0-9]{10}[^"\']*',
        r'https:\\/\\/www\.amazon\.com\.br\\/[^"\']*\\/dp\\/[A-Z0-9]{10}[^"\']*',
        r'https:\\/\\/www\.amazon\.com\.br\\/dp\\/[A-Z0-9]{10}[^"\']*',
        r'https:\\/\\/www\.amazon\.com\.br\\/gp\\/product\\/[A-Z0-9]{10}[^"\']*',
    ]
    for pattern in patterns:
        for raw_match in re.findall(pattern, html_text or "", re.IGNORECASE):
            url = str(raw_match or "").replace("\\/", "/").replace("&amp;", "&").strip()
            if not url.startswith("https://www.amazon.com.br/"):
                continue
            cleaned = _clean_amazon_url(url, tag)
            if cleaned in seen:
                continue
            seen.add(cleaned)
            links.append(cleaned)
            if len(links) >= limit:
                return links
    return links


def _extract_ml_item_id(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    return (fragment.get("wid") or query.get("wid") or [None])[0]


def _extract_ml_product_id(url: str) -> str | None:
    match = re.search(r"/p/(MLB\d+)", (url or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _keyword_from_page_url(url: str) -> str:
    path = (urlparse((url or "").strip()).path or "").strip("/")
    if not path:
        return ""
    parts = [part for part in path.split("/") if part and part.lower() not in {"gp", "bestsellers"}]
    if not parts:
        return ""
    candidate = parts[-1]
    candidate = re.sub(r"[^a-z0-9-]+", "-", candidate.lower()).strip("-")
    return candidate.replace("-", " ").strip()


def _extract_amazon_asin(url: str) -> str | None:
    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", (url or "").strip(), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _strip_html(value: str) -> str:
    text = re.sub(r"<script[\s\S]*?</script>", " ", value or "", flags=re.IGNORECASE)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_amazon_saved_html_items(html_text: str, limit: int, tag: str | None, source_name: str) -> list[dict[str, Any]]:
    links = _extract_amazon_listing_product_links(html_text, limit * 3, tag)
    if not links:
        return []

    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in links:
        if link in seen:
            continue
        seen.add(link)
        asin = _extract_amazon_asin(link)
        if not asin:
            continue

        asin_pattern = re.escape(asin)
        block_match = re.search(
            rf'(<[^>]+(?:dp|gp/product)/{asin_pattern}[\s\S]{{0,4500}}?</(?:li|div|article)>)',
            html_text,
            re.IGNORECASE,
        )
        block = block_match.group(1) if block_match else html_text[max(0, html_text.find(asin) - 1200): html_text.find(asin) + 3600]

        title = _clean_title(
            _extract_first(
                block,
                [
                    r'aria-label=["\']([^"\']+)["\']',
                    r'alt=["\']([^"\']+)["\']',
                    r'<a[^>]*>(.*?)</a>',
                ],
            ),
            "amazon",
        )
        title = _strip_html(title)
        if not title or len(title) < 6:
            continue

        image = _extract_first(
            block,
            [
                r'<img[^>]+src=["\']([^"\']+)["\']',
                r'"hiRes":"([^"]+)"',
                r'"large":"([^"]+)"',
            ],
        ).replace("\\u0026", "&").replace("\\/", "/")

        description = _strip_html(
            _extract_first(
                block,
                [
                    r'<span[^>]*class=["\'][^"\']*a-size-base[^"\']*["\'][^>]*>(.*?)</span>',
                    r'<div[^>]*class=["\'][^"\']*p13n-sc-truncate[^"\']*["\'][^>]*>(.*?)</div>',
                ],
            )
        ) or f"Oferta Amazon importada de HTML salvo: {source_name or 'arquivo'}."

        price_raw = _extract_first(
            block,
            [
                r'a-price-whole">\s*([\d\.,]+).*?a-price-fraction">\s*([\d]{2})',
                r'a-offscreen">\s*R\$\s*([\d\.,]+)',
                r'R\$\s*([\d\.,]+)',
            ],
        )
        if re.search(r'a-price-whole">\s*([\d\.,]+).*?a-price-fraction">\s*([\d]{2})', block, re.IGNORECASE | re.DOTALL):
            pair = re.search(r'a-price-whole">\s*([\d\.,]+).*?a-price-fraction">\s*([\d]{2})', block, re.IGNORECASE | re.DOTALL)
            price_raw = f"{pair.group(1)},{pair.group(2)}"
        price = _normalize_price(price_raw)
        if price <= 0:
            visible_prices = [_normalize_price(value) for value in _extract_all(block, [r'R\$\s*([\d\.,]+)'])]
            visible_prices = [value for value in visible_prices if value > 0]
            if visible_prices:
                price = visible_prices[0]
        if price <= 0:
            continue

        old_price = _normalize_price(
            _extract_first(
                block,
                [
                    r'"listPriceAmount"\s*:\s*"?(\\?[\d\.,]+)"?',
                    r'a-text-price[^>]*>\s*<span[^>]*>\s*R\$\s*([\d\.,]+)',
                ],
            )
        )

        affiliate_detected, affiliate_code = _detect_affiliate(link)
        items.append(
            {
                "provider": "amazon",
                "store": "Amazon",
                "title": title,
                "description": description,
                "price": price,
                "old_price": old_price if old_price > price > 0 else None,
                "url": link,
                "canonical_url": link,
                "image": image,
                "category": infer_category_label(title, description, link, default="ofertas"),
                "tags": "amazon,arquivo,html",
                "featured": 0,
                "affiliate_detected": affiliate_detected,
                "affiliate_code": affiliate_code or tag,
                "selected": True,
                "source_file": source_name,
                "item_id": None,
                "product_id": asin,
            }
        )
        if len(items) >= limit:
            break

    return items


def preview_amazon_saved_html(content: bytes, filename: str = "", limit: int = 10) -> list[dict[str, Any]]:
    if not content:
        raise ValueError("Envie um arquivo HTML salvo da Amazon.")

    capped_limit = max(1, min(int(limit or 10), 30))
    html_text = content.decode("utf-8", errors="replace")
    tag = (os.getenv("AMAZON_AFFILIATE_TAG") or "").strip() or None
    direct_items = _extract_amazon_saved_html_items(html_text, capped_limit, tag, filename)
    if direct_items:
        return direct_items

    links = _extract_amazon_listing_product_links(html_text, capped_limit, tag)
    if not links:
        raise ValueError("Nao foi possivel identificar links de produto nesse HTML salvo da Amazon.")

    items = preview_manual_affiliate_links(links[:capped_limit])
    enriched: list[dict[str, Any]] = []
    for item in items:
        source_url = item.get("url") or item.get("canonical_url") or ""
        canonical_url = item.get("canonical_url") or source_url
        enriched.append(
            {
                **item,
                "selected": True,
                "source_file": filename,
                "item_id": None,
                "product_id": _extract_amazon_asin(canonical_url or source_url),
            }
        )
    return enriched


def preview_page_url(page_url: str, limit: int = 10) -> tuple[str, list[dict[str, Any]]]:
    normalized_url = (page_url or "").strip()
    if not normalized_url:
        raise ValueError("Informe a URL de uma pagina do Mercado Livre ou da Amazon.")

    provider = _normalize_provider_from_url(normalized_url)
    capped_limit = max(1, min(int(limit or 10), 30))

    try:
        with httpx.Client(timeout=25, headers=_browser_headers(), follow_redirects=True) as client:
            response = client.get(normalized_url)
            response.raise_for_status()
            html_text = response.text
    except httpx.HTTPStatusError as exc:
        if provider == "amazon":
            raise ValueError("A Amazon bloqueou a leitura automatica desta pagina agora. Tente outra vitrine, menos itens ou use links de produto/TXT.") from exc
        raise ValueError("O Mercado Livre bloqueou a leitura automatica desta pagina agora. Tente novamente em instantes ou use outra listagem.") from exc

    links: list[str]
    if provider == "mercadolivre":
        links = _extract_ml_listing_product_links(html_text, capped_limit)
        if links:
            items = preview_manual_affiliate_links(links[:capped_limit])
        else:
            keyword = _keyword_from_page_url(normalized_url)
            if not keyword:
                raise ValueError("Nao foi possivel identificar produtos afiliados nessa pagina do Mercado Livre.")
            try:
                items = preview_mercadolivre_offers(keyword=keyword, limit=min(capped_limit, 10), pages=1)
            except httpx.HTTPError as exc:
                raise ValueError("A pagina nao expôs os links e a busca publica do Mercado Livre foi bloqueada agora. Tente outra pagina ou mais tarde.") from exc
    else:
        tag = (parse_qs(urlparse(normalized_url).query).get("tag") or [os.getenv("AMAZON_AFFILIATE_TAG", "").strip() or None])[0]
        links = _extract_amazon_listing_product_links(html_text, capped_limit, tag)
        if not links:
            raise ValueError("Nao foi possivel identificar links de produto nessa pagina da Amazon. A vitrine pode ter sido bloqueada ou renderizada de outro jeito.")
        items = preview_manual_affiliate_links(links[:capped_limit])
    enriched: list[dict[str, Any]] = []
    for item in items:
        source_url = item.get("url") or item.get("canonical_url") or ""
        canonical_url = item.get("canonical_url") or source_url
        if provider == "mercadolivre":
            enriched.append(
                {
                    **item,
                    "title": _clean_ml_title(str(item.get("title") or "")) or "Oferta Mercado Livre",
                    "selected": True,
                    "source_page_url": normalized_url,
                    "item_id": item.get("item_id") or _extract_ml_item_id(source_url),
                    "product_id": item.get("product_id") or _extract_ml_product_id(canonical_url or source_url),
                }
            )
        else:
            enriched.append(
                {
                    **item,
                    "selected": True,
                    "source_page_url": normalized_url,
                    "item_id": None,
                    "product_id": _extract_amazon_asin(canonical_url or source_url),
                }
            )

    return provider, enriched
