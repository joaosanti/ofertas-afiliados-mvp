import re
import time
from collections import Counter
from html import unescape
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse

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
    host = (parsed.netloc or "").lower()
    query = parse_qs(parsed.query, keep_blank_values=True)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    combined = {**query, **fragment}

    wid = (combined.get("wid") or [None])[0]
    sid = (combined.get("sid") or [None])[0]
    polycard_client = (combined.get("polycard_client") or [None])[0]
    matt_tool = (combined.get("matt_tool") or [None])[0]
    source = (combined.get("source") or [None])[0]
    reco_client = (combined.get("reco_client") or [None])[0]
    tracking_id = (combined.get("tracking_id") or [None])[0]
    reco_id = (combined.get("reco_id") or [None])[0]
    matt_tracing_id = (combined.get("matt_tracing_id") or [None])[0]
    is_social = "/social/" in (parsed.path or "").lower()
    is_short = host == "meli.la"
    affiliate_profile_marker = any(
        "affiliate" in str(value or "").lower()
        for value in (source, polycard_client, reco_client)
    )
    recommendation_marker = bool(
        wid
        and (
            sid
            or tracking_id
            or reco_id
            or matt_tracing_id
            or affiliate_profile_marker
        )
    )

    strong = bool(
        matt_tool
        or is_social
        or is_short
        or recommendation_marker
        or affiliate_profile_marker
    )
    detected = bool(strong)
    code = matt_tool or wid or tracking_id

    warning = None
    if not detected:
        warning = (
            "Link do Mercado Livre sem marcador forte de afiliado. "
            "Use o social/matt_tool ou o shortlink oficial gerado na Central."
        )

    return {
        "official": strong,
        "detected": detected,
        "status": "official" if strong else "missing",
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


def _safe_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace('.', '').replace(',', '.')))
    except ValueError:
        return None


def _clean_snippet(value: Any, limit: int = 160) -> str | None:
    text = re.sub(r"\s+", " ", unescape(str(value or ""))).strip(" -:|,.")
    if not text:
        return None
    return text[:limit]


def _html_plain_text(html_text: str) -> str:
    content = re.sub(r"<script[\s\S]*?</script>", " ", html_text or "", flags=re.IGNORECASE)
    content = re.sub(r"<style[\s\S]*?</style>", " ", content, flags=re.IGNORECASE)
    content = re.sub(r"<[^>]+>", " ", content)
    return re.sub(r"\s+", " ", unescape(content)).strip()


def _discount_percent(price: Any, old_price: Any) -> int | None:
    current = _normalize_price(price)
    previous = _normalize_price(old_price)
    if current <= 0 or previous <= current:
        return None
    return int(round(((previous - current) / previous) * 100))


def _extract_amazon_offer_metadata(html_text: str, price: Any, old_price: Any) -> dict[str, Any]:
    plain = _html_plain_text(html_text)
    rating = _safe_float(_extract_first(plain, [
        r"([0-5][\.,][0-9])\s+de\s+5\s+estrelas",
        r"([0-5][\.,][0-9])\s+de\s+5",
    ]))
    rating_count = _safe_int(_extract_first(plain, [
        r"([\d\.,]+)\s+avaliac(?:ao|oes)",
        r"([\d\.,]+)\s+classificac(?:ao|oes)",
    ]))
    installments = _clean_snippet(_extract_first(plain, [
        r"((?:em ate|ate)\s+\d+x\s+de\s+R\$\s*[\d\.,]+(?:\s+sem juros)?)",
        r"(\d+x\s+de\s+R\$\s*[\d\.,]+(?:\s+sem juros)?)",
    ]))
    shipping = _clean_snippet(_extract_first(plain, [
        r"(Entrega GRATIS[^\.]{0,80})",
        r"(Frete GRATIS[^\.]{0,80})",
        r"(Entrega gratis[^\.]{0,80})",
        r"(Frete gratis[^\.]{0,80})",
    ]))
    promo_bits = []
    for pattern in [
        r"(R\$\s*[\d\.,]+\s*off[^\.]{0,90})",
        r"(Mais por Menos:[^\.]{0,110})",
        r"(Cupom de desconto[^\.]{0,110})",
    ]:
        value = _clean_snippet(_extract_first(plain, [pattern]), 120)
        if value and value not in promo_bits:
            promo_bits.append(value)
    discount_percent = _safe_int(_extract_first(plain, [r"-?(\d{1,2})%"])) or _discount_percent(price, old_price)
    return {
        "discount_percent": discount_percent,
        "installments": installments,
        "shipping": shipping,
        "rating": rating,
        "rating_count": rating_count,
        "promotion_text": " | ".join(promo_bits[:2]) or None,
    }


def _extract_ml_offer_metadata(html_text: str, price: Any, old_price: Any) -> dict[str, Any]:
    plain = _html_plain_text(html_text)
    discount_percent = _safe_int(_extract_first(plain, [r"(\d{1,2})%\s*OFF"])) or _discount_percent(price, old_price)
    pix_price = _normalize_price(_extract_first(plain, [
        r"R\$\s*([\d\.,]+)\s*(?:\d{1,2}%\s*OFF\s*)?no Pix",
        r"no Pix ou[^R]{0,20}R\$\s*([\d\.,]+)",
    ])) or None
    if pix_price is None and "no pix" in plain.lower() and _normalize_price(price) > 0:
        pix_price = _normalize_price(price)
    other_price = _normalize_price(_extract_first(plain, [r"R\$\s*([\d\.,]+)\s*em outros meios"])) or None
    installments = _clean_snippet(_extract_first(plain, [
        r"((?:em|por)\s+\d+x(?:\s+de)?\s*R\$\s*[\d\.,]+(?:\s+sem juros)?)",
        r"(\d+x(?:\s+de)?\s*R\$\s*[\d\.,]+(?:\s+sem juros)?)",
        r"(\d+x\s*R\$\s*[\d\.,]+(?:\s+sem juros)?)",
    ]))
    shipping = _clean_snippet(_extract_first(plain, [
        r"(Chegara gratis[^\.]{0,80})",
        r"(Frete gratis[^\.]{0,80})",
        r"(Frete GRATIS[^\.]{0,80})",
    ]))
    rating = _safe_float(_extract_first(plain, [
        r"Avaliacao\s*([0-5][\.,][0-9])\s*de\s*5",
        r"([0-5][\.,][0-9])\s+de\s+5",
    ]))
    rating_count = _safe_int(_extract_first(plain, [
        r"Avaliacao\s*[0-5][\.,][0-9]\s*de\s*5[^\d]{0,20}([\d\.,]+)",
        r"\(([\d\.,]+)\)",
    ]))
    promotion_text = _clean_snippet(_extract_first(plain, [
        r"(\d{1,2}%\s*OFF[^\.]{0,120})",
        r"(no Pix ou Saldo no Mercado Pago[^\.]{0,120})",
    ]), 140)
    return {
        "discount_percent": discount_percent,
        "pix_price": pix_price,
        "other_price": other_price,
        "installments": installments,
        "shipping": shipping,
        "rating": rating,
        "rating_count": rating_count,
        "promotion_text": promotion_text,
    }


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
    if "mercadolivre" in host or "mercadolibre" in host or host == "meli.la":
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


def _extract_ml_item_id_from_url(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    query = parse_qs(parsed.query, keep_blank_values=True)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    combined = {**query, **fragment}
    for key in ("wid", "item_id", "item"):
        candidate = str((combined.get(key) or [None])[0] or "").strip()
        match = re.search(r"(MLB)[-_]?(\d+)", candidate, re.IGNORECASE)
        if match:
            return f"{match.group(1).upper()}{match.group(2)}"
    match = re.search(r"(MLB)[-_]?(\d+)", (url or "").strip(), re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).upper()}{match.group(2)}"


def _is_ml_social_link(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    return ("mercadolivre" in host or "mercadolibre" in host) and "/social/" in (parsed.path or "").lower()


def _looks_like_ml_product_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    if "mercadolivre" not in host and "mercadolibre" not in host:
        return False
    path = unquote(parsed.path or "")
    lowered = path.lower()
    if "/social/" in lowered or "/registration" in lowered or "/jms/" in lowered:
        return False
    return bool(
        re.search(r"/p/(MLB\d+)", path, re.IGNORECASE)
        or re.search(r"/MLB[-_]?(\d+)", path, re.IGNORECASE)
        or re.search(r"/(?:item|produto)/MLB[-_]?(\d+)", path, re.IGNORECASE)
    )


def _normalize_ml_candidate_url(raw_value: str, base_url: str) -> str:
    value = unescape(str(raw_value or "").strip())
    value = value.replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
    if not value:
        return ""
    if value.startswith("//"):
        value = f"https:{value}"
    elif value.startswith("/"):
        value = urljoin(base_url, value)
    if not value.startswith(("http://", "https://")):
        return ""
    return value.strip()


def _extract_ml_product_links_from_html(html_text: str, base_url: str, limit: int = 8) -> list[str]:
    patterns = [
        r'https?://[^"\'\s<>\\]*mercadolivre\.com\.br/[^"\'\s<>\\]+',
        r'https?://[^"\'\s<>\\]*mercadolibre\.com/[^"\'\s<>\\]+',
        r'https?:\\/\\/[^"\'\s<>]*mercadolivre\.com\.br\\/[^"\'\s<>]+',
        r'https?:\\/\\/[^"\'\s<>]*mercadolibre\.com\\/[^"\'\s<>]+',
        r'href=["\']([^"\']*(?:/p/MLB\d+|/MLB[-_]?\d+[^"\']*))["\']',
        r'"url"\s*:\s*"([^"]*(?:/p/MLB\d+|/MLB[-_]?\d+[^"]*))"',
        r'"permalink"\s*:\s*"([^"]*(?:/p/MLB\d+|/MLB[-_]?\d+[^"]*))"',
    ]
    found: list[str] = []
    seen: set[str] = set()

    for pattern in patterns:
        for match in re.findall(pattern, html_text or "", re.IGNORECASE):
            candidate = _normalize_ml_candidate_url(match, base_url)
            if not candidate or not _looks_like_ml_product_url(candidate) or candidate in seen:
                continue
            seen.add(candidate)
            found.append(candidate)
            if len(found) >= limit:
                break
        if len(found) >= limit:
            break

    found.sort(
        key=lambda item: (
            0 if _meli_affiliate_meta(item).get("official") else 1,
            0 if "/p/" in (urlparse(item).path or "").lower() else 1,
            item,
        )
    )
    return found


def _looks_like_real_ml_description(text: str) -> bool:
    value = re.sub(r"\s+", " ", str(text or "").strip())
    if not value:
        return False
    generic_markers = (
        "visite a pagina e encontre todos os produtos",
        "oferta mercado livre importada",
        "pagina bloqueou a leitura automatica",
        "revise preco, imagem e descricao antes de importar",
        "perfil social oficial",
    )
    lowered = value.lower()
    return not any(marker in lowered for marker in generic_markers)


def _extract_ml_real_description(html_text: str) -> str:
    description = _extract_first(
        html_text,
        [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:description["\'][^>]+content=["\']([^"\']+)["\']',
        ],
    )
    description = re.sub(r"\s+", " ", description).strip()
    return description if _looks_like_real_ml_description(description) else ""


def _fetch_ml_product_description(url: str) -> str:
    try:
        _, product_html = _fetch_best_html_for_provider(url, "mercadolivre")
    except Exception:
        return ""
    return _extract_ml_real_description(product_html)


def _extract_ml_trigger_item_id_from_html(html_text: str) -> str | None:
    patterns = [
        r'"product_id":"(MLB\d+)"',
        r'"item_id":"(MLB\d+)"',
        r'"wid":"(MLB\d+)"',
    ]
    for pattern in patterns:
        match = re.search(pattern, html_text or "", re.IGNORECASE)
        if match:
            return str(match.group(1) or "").upper()
    return None


def _decode_ml_embedded_text(value: str) -> str:
    text = str(value or "")
    replacements = {
        "\\u002F": "/",
        "\\u0026": "&",
        "\\u003D": "=",
        "\\u002B": "+",
        "\\u002D": "-",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return unescape(text)


def _extract_ml_social_embedded_offer(html_text: str, affiliate_url: str) -> dict[str, Any] | None:
    trigger_product_id = _extract_ml_trigger_item_id_from_html(html_text)
    if not trigger_product_id:
        return None

    product_match = re.search(rf'"product_id":"{re.escape(trigger_product_id)}"', html_text or "", re.IGNORECASE)
    if not product_match:
        return None

    window_start = max(0, product_match.start() - 600)
    window_end = min(len(html_text), product_match.end() + 5000)
    segment = (html_text or "")[window_start:window_end]

    meta_match = re.search(
        rf'"metadata":\{{"id":"(MLB\d+)","product_id":"{re.escape(trigger_product_id)}".*?"url":"([^"]+)".*?"url_fragments":"([^"]*)".*?"url_params":"([^"]*)"',
        segment,
        re.IGNORECASE | re.DOTALL,
    )
    if not meta_match:
        return None

    item_id = str(meta_match.group(1) or "").upper()
    url_path = _decode_ml_embedded_text(meta_match.group(2))
    url_fragments = _decode_ml_embedded_text(meta_match.group(3))
    url_params = _decode_ml_embedded_text(meta_match.group(4))

    title_match = re.search(r'"title":\{"text":"([^"]+)"', segment, re.IGNORECASE)
    current_price_match = re.search(r'"current_price":\{"value":([0-9]+(?:\.[0-9]+)?)', segment, re.IGNORECASE)
    previous_price_match = re.search(r'"previous_price":\{"value":([0-9]+(?:\.[0-9]+)?)', segment, re.IGNORECASE)
    image_match = re.search(r'"meta(?:_)?tags":\[[^\]]*"og:image","content":"([^"]+)"', html_text or "", re.IGNORECASE)

    title = _decode_ml_embedded_text(title_match.group(1)) if title_match else _clean_title(
        _extract_first(
            html_text,
            [
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
            ],
        ),
        "mercadolivre",
    )
    if not title or not current_price_match:
        return None

    final_affiliate_url = affiliate_url
    if url_path:
        if not url_path.startswith("http"):
            url_path = f"https://{url_path.lstrip('/')}"
        final_affiliate_url = f"{url_path}{url_params}{url_fragments}"

    meta = _meli_affiliate_meta(final_affiliate_url)
    image_url = (
        _decode_ml_embedded_text(image_match.group(1))
        if image_match
        else _extract_first(
            html_text,
            [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            ],
        )
    )
    description = _fetch_ml_product_description(final_affiliate_url)
    commerce_metadata = _extract_ml_offer_metadata(
        html_text,
        float(current_price_match.group(1)),
        float(previous_price_match.group(1)) if previous_price_match else None,
    )

    social_source_url = affiliate_url if _is_ml_social_link(affiliate_url) else ""

    return {
        "provider": "mercadolivre",
        "store": "Mercado Livre",
        "title": title,
        "description": description,
        "price": float(current_price_match.group(1)),
        "old_price": float(previous_price_match.group(1)) if previous_price_match else None,
        "url": social_source_url or final_affiliate_url,
        "canonical_url": final_affiliate_url,
        "image": image_url,
        "category": infer_category_label(title, description or title, final_affiliate_url, final_affiliate_url, default="ofertas"),
        "tags": "mercadolivre,manual,social",
        "featured": 0,
        "affiliate_detected": bool(meta["detected"]),
        "affiliate_code": meta["code"],
        "affiliate_status": str(meta["status"]),
        "affiliate_warning": "Produto resolvido diretamente do HTML do perfil social do Mercado Livre." if meta["official"] else meta["warning"],
        "import_allowed": bool(meta["detected"]),
        "item_id": item_id,
        "product_id": trigger_product_id,
        "social_url": social_source_url or None,
        **commerce_metadata,
    }


def _build_ml_offer_from_api(item_id: str, affiliate_url: str, fallback_html: str = "") -> dict[str, Any]:
    meta = _meli_affiliate_meta(affiliate_url)
    description = _fetch_ml_product_description(affiliate_url)
    with httpx.Client(timeout=20, headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "pt-BR,pt;q=0.9"}) as client:
        response = client.get(f"https://api.mercadolibre.com/items/{item_id}")
        response.raise_for_status()
        payload = response.json()

    title = str(payload.get("title") or "").strip() or _clean_title(
        _extract_first(
            fallback_html,
            [
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+name=["\']title["\'][^>]+content=["\']([^"\']+)["\']',
            ],
        ),
        "mercadolivre",
    )
    if not title:
        raise ValueError("Nao foi possivel resolver o titulo do produto do Mercado Livre pela API.")

    image = (
        str(payload.get("thumbnail") or "").strip()
        or str(((payload.get("pictures") or [{}])[0] or {}).get("secure_url") or "").strip()
        or str(((payload.get("pictures") or [{}])[0] or {}).get("url") or "").strip()
        or _extract_first(
            fallback_html,
            [
                r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
            ],
        )
    )
    canonical_hint = str(payload.get("permalink") or "").strip() or affiliate_url
    price = float(payload.get("price") or 0)
    old_price = float(payload["original_price"]) if payload.get("original_price") else None
    commerce_metadata = _extract_ml_offer_metadata(fallback_html or "", price, old_price)
    if not commerce_metadata.get("shipping") and bool(((payload.get("shipping") or {}).get("free_shipping"))):
        commerce_metadata["shipping"] = "Frete gr?tis"
    if not commerce_metadata.get("discount_percent"):
        commerce_metadata["discount_percent"] = _discount_percent(price, old_price)
    social_source_url = affiliate_url if _is_ml_social_link(affiliate_url) else ""

    return {
        "provider": "mercadolivre",
        "store": "Mercado Livre",
        "title": title,
        "description": description,
        "price": price,
        "old_price": old_price,
        "url": social_source_url or affiliate_url,
        "canonical_url": canonical_hint,
        "image": image,
        "category": infer_category_label(title, description or title, social_source_url or affiliate_url, canonical_hint, default="ofertas"),
        "tags": "mercadolivre,manual,social",
        "featured": 0,
        "affiliate_detected": bool(meta["detected"]),
        "affiliate_code": meta["code"],
        "affiliate_status": str(meta["status"]),
        "affiliate_warning": "Dados do produto resolvidos pela API do Mercado Livre a partir do link oficial." if meta["official"] else meta["warning"],
        "import_allowed": bool(meta["detected"]),
        "item_id": item_id,
        "product_id": str(payload.get("catalog_product_id") or "").strip() or _extract_ml_product_id_from_url(canonical_hint),
        "social_url": social_source_url or None,
        **commerce_metadata,
    }


def _resolve_ml_social_offer(link: str) -> dict[str, Any]:
    social_url, social_html = _fetch_best_html_for_provider(link, "mercadolivre")
    embedded_offer = _extract_ml_social_embedded_offer(social_html, link)
    if embedded_offer:
        embedded_offer["social_url"] = social_url
        embedded_offer["url"] = social_url
        embedded_offer["canonical_url"] = embedded_offer.get("canonical_url") or embedded_offer.get("url") or social_url
        return embedded_offer
    trigger_item_id = _extract_ml_trigger_item_id_from_html(social_html)
    if trigger_item_id:
        try:
            item = _build_ml_offer_from_api(trigger_item_id, link, social_html)
            item["social_url"] = social_url
            item["url"] = social_url
            item["canonical_url"] = item.get("canonical_url") or item.get("url") or social_url
            return item
        except Exception:
            pass
    product_links = _extract_ml_product_links_from_html(social_html, social_url)
    if not product_links:
        raise ValueError("Nao foi possivel localizar um produto valido dentro desse link social do Mercado Livre.")

    last_error: Exception | None = None
    for product_link in product_links:
        html_text = ""
        try:
            final_url, html_text = _fetch_best_html_for_provider(product_link, "mercadolivre")
            affiliate_source = product_link if _meli_affiliate_meta(product_link).get("detected") else link
            item = _extract_generic_offer("mercadolivre", affiliate_source, final_url, html_text)
            item["social_url"] = social_url
            item["canonical_url"] = final_url or product_link or item.get("canonical_url") or item.get("url") or social_url
            item["url"] = social_url
            item["item_id"] = item.get("item_id") or _extract_ml_item_id_from_url(product_link) or _extract_ml_item_id_from_url(final_url)
            item["product_id"] = item.get("product_id") or _extract_ml_product_id_from_url(final_url) or _extract_ml_product_id_from_url(product_link)
            if social_url != link:
                item["affiliate_warning"] = "Produto extraido automaticamente de uma pagina social oficial do Mercado Livre."
            return item
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            try:
                resolved_item_id = _extract_ml_item_id_from_url(product_link) or _extract_ml_trigger_item_id_from_html(html_text)
                if resolved_item_id:
                    return _build_ml_offer_from_api(resolved_item_id, link, social_html)
            except Exception:
                pass

    if last_error is not None:
        raise last_error
    raise ValueError("Nao foi possivel abrir o produto destacado desse link social do Mercado Livre.")


def _build_ml_fallback_offer(link: str) -> dict[str, Any]:
    meta = _meli_affiliate_meta(link)
    title = _extract_ml_title_from_url(link)
    return {
        "provider": "mercadolivre",
        "store": "Mercado Livre",
        "title": title,
        "description": "",
        "price": 0.0,
        "old_price": None,
        "url": link,
        "canonical_url": link,
        "image": "",
        "category": infer_category_label(title, title, link, link, default="ofertas"),
        "tags": "mercadolivre,manual,fallback",
        "featured": 0,
        "affiliate_detected": bool(meta["detected"]),
        "affiliate_code": meta["code"],
        "affiliate_status": str(meta["status"]),
        "affiliate_warning": (
            "Link oficial detectado, mas o Mercado Livre bloqueou a leitura automatica. Revise os dados antes de importar."
            if meta["official"]
            else meta["warning"]
        ),
        "import_allowed": bool(meta["detected"]),
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
        return (bool(meta["detected"]), meta["code"])
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
    if provider == "mercadolivre":
        description = _extract_ml_real_description(html_text)

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
    commerce_metadata: dict[str, Any] = {}
    if provider == "amazon":
        commerce_metadata = _extract_amazon_offer_metadata(html_text, price, old_price)
    elif provider == "mercadolivre":
        commerce_metadata = _extract_ml_offer_metadata(html_text, price, old_price)

    affiliate_detected, affiliate_code = _detect_affiliate(final_url or source_url)
    import_allowed = True
    affiliate_warning = None
    affiliate_status = "ok" if affiliate_detected else "missing"
    if provider == "mercadolivre":
        meta = _meli_affiliate_meta(source_url)
        affiliate_detected = bool(meta["detected"])
        affiliate_code = meta["code"]
        affiliate_warning = meta["warning"]
        import_allowed = affiliate_detected
        affiliate_status = str(meta["status"])

    return {
        "provider": provider,
        "store": _provider_label(provider),
        "title": title,
        "description": description or ("" if provider == "mercadolivre" else f"Oferta {_provider_label(provider)} importada manualmente."),
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
        **commerce_metadata,
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
                        "video_url": item.get("video_url"),
                        "affiliate_detected": affiliate_detected,
                        "affiliate_code": affiliate_code,
                    }
                )
            continue

        if provider == "mercadolivre" and urlparse(link).netloc.lower() == "meli.la":
            try:
                final_url, _ = _fetch_best_html_for_provider(link, "mercadolivre")
                link = final_url or link
            except Exception:
                pass

        if provider == "mercadolivre" and _is_ml_social_link(link):
            try:
                items.append(_resolve_ml_social_offer(link))
            except Exception:
                try:
                    final_url, html_text = _fetch_best_html_for_provider(link, "mercadolivre")
                    items.append(_extract_generic_offer("mercadolivre", final_url or link, final_url, html_text))
                    continue
                except Exception:
                    pass
                if _meli_affiliate_meta(link)["detected"]:
                    items.append(_build_ml_fallback_offer(link))
                    continue
                raise
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
            if provider == "mercadolivre" and _meli_affiliate_meta(link)["detected"]:
                try:
                    resolved_item_id = _extract_ml_item_id_from_url(link)
                    if resolved_item_id:
                        items.append(_build_ml_offer_from_api(resolved_item_id, link))
                        continue
                except Exception:
                    pass
            if provider == "mercadolivre" and _meli_affiliate_meta(link)["detected"]:
                items.append(_build_ml_fallback_offer(link))
                continue
            if provider == "amazon":
                affiliate_detected, _ = _detect_affiliate(link)
                if affiliate_detected:
                    items.append(_build_amazon_fallback_offer(link))
                    continue
            raise

    return items
