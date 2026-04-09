import hashlib
import json
import os
import re
import time
import unicodedata
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from dotenv import load_dotenv

from app.services.category_inference import infer_category_label

try:
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
except Exception:  # noqa: BLE001
    PlaywrightTimeoutError = Exception
    sync_playwright = None


class ShopeeBlockedError(ValueError):
    def __init__(self, message: str, *, source: str = "shopee", retry_after_seconds: int | None = None):
        super().__init__(message)
        self.source = source
        self.retry_after_seconds = retry_after_seconds


SHOPEE_API_URL = "https://open-api.affiliate.shopee.com.br/graphql"
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
DEFAULT_QUERY = """
query ProductOfferQuery($keyword: String!, $limit: Int!, $page: Int!, $sortType: Int!) {
  productOfferV2(keyword: $keyword, limit: $limit, page: $page, sortType: $sortType) {
    nodes {
      itemId
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
      priceDiscountRate
    }
    pageInfo {
      page
      limit
    }
  }
}
""".strip()


def _reload_shopee_env() -> None:
    load_dotenv(dotenv_path=ENV_PATH, override=True)

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


def _extract_first(content: str, patterns: list[str]) -> str:
    for pattern in patterns:
        match = re.search(pattern, content, re.IGNORECASE | re.DOTALL)
        if match:
            return unescape((match.group(1) or "").strip())
    return ""


def _extract_all(content: str, patterns: list[str]) -> list[str]:
    values: list[str] = []
    for pattern in patterns:
        values.extend(unescape((match or "").strip()) for match in re.findall(pattern, content, re.IGNORECASE | re.DOTALL))
    return [value for value in values if value]


def _clean_media_url(value: str) -> str:
    media_url = unescape(str(value or "").strip())
    if not media_url:
        return ""
    media_url = media_url.replace("\\/", "/").replace("\\u0026", "&").replace("&amp;", "&")
    if media_url.startswith("//"):
        media_url = f"https:{media_url}"
    return media_url if media_url.startswith(("http://", "https://")) else ""


def _normalize_shopee_image_candidate(value: str) -> str:
    normalized = _clean_media_url(value)
    if normalized:
        normalized = re.sub(r"@resize_[^/?#]+", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"@aspect_[^/?#]+", "", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"_(?:tn|thumbnail)(?=$|[?#])", "", normalized, flags=re.IGNORECASE)
        return normalized

    candidate = unescape(str(value or "").strip()).strip('"').strip("'")
    if not candidate:
        return ""
    if re.fullmatch(r"(?:[a-z]{2,4}-)?[\w-]{18,120}", candidate, re.IGNORECASE):
        return f"https://down-br.img.susercontent.com/file/{candidate}"
    return ""


def _dedupe_media_urls(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(url)
    return deduped


def _prioritize_reachable_video_urls(urls: list[str]) -> list[str]:
    normalized = _dedupe_media_urls([_clean_media_url(url) for url in urls])
    if len(normalized) <= 1:
        return normalized

    reachable: list[str] = []
    unknown: list[str] = []
    dead: list[str] = []
    headers = {"User-Agent": "Mozilla/5.0"}

    for url in normalized[:4]:
        try:
            with httpx.Client(follow_redirects=True, timeout=8.0, headers=headers) as client:
                response = client.head(url)
                if response.status_code >= 400 or response.status_code == 405:
                    response = client.get(url, headers={"Range": "bytes=0-1", **headers})
            if 200 <= response.status_code < 400:
                reachable.append(url)
            else:
                dead.append(url)
        except Exception:  # noqa: BLE001
            unknown.append(url)

    remaining = [url for url in normalized if url not in reachable and url not in unknown and url not in dead]
    prioritized = reachable + unknown + remaining + dead
    return _dedupe_media_urls(prioritized)


def _is_shopee_gallery_image(url: str) -> bool:
    value = _clean_media_url(url)
    if not value:
        return False
    lowered = value.lower()
    if lowered.endswith(".svg"):
        return False
    if "/assets/" in lowered and "img.susercontent.com/file/" not in lowered:
        return False
    return any(
        token in lowered
        for token in (
            "img.susercontent.com/file/",
            "cf.shopee.com.br/file/",
            "down-br.img.susercontent.com/file/",
            "down-tx-br.img.susercontent.com/file/",
        )
    )


def _extract_shopee_ids_from_url(url: str) -> tuple[str, str] | None:
    raw = str(url or "").strip()
    if not raw:
        return None
    patterns = [
        r"/product/(\d+)/(\d+)",
        r"/opaanlp/(\d+)/(\d+)",
        r"/i\.(\d+)\.(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, re.IGNORECASE)
        if match:
            return match.group(1), match.group(2)
    return None


def _looks_like_shopee_product_url(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    return "shopee.com.br/" in lowered and _extract_shopee_ids_from_url(raw) is not None


def _build_shopee_product_url(shop_id: Any, item_id: Any) -> str:
    shop = str(shop_id or "").strip()
    item = str(item_id or "").strip()
    if not shop or not item:
        return ""
    return f"https://shopee.com.br/product/{shop}/{item}"


def _offer_media_score(offer: dict[str, Any]) -> tuple[int, int, int, int]:
    image_urls = [
        url for url in (offer.get("image_urls") or [])
        if _is_shopee_gallery_image(url)
    ]
    video_urls = [url for url in (offer.get("video_urls") or []) if _clean_media_url(url)]
    return (
        1 if video_urls else 0,
        len(image_urls),
        1 if float(offer.get("price") or 0) > 0 else 0,
        len(str(offer.get("description") or "").strip()),
    )


def _extract_browser_dom_offer(page: Any, source_url: str) -> dict[str, Any]:
    final_url = _unwrap_shopee_login_redirect(str(page.url or source_url))
    title = ""
    try:
        h1_values = page.locator("h1").all_inner_texts()
        title = next((str(item or "").strip() for item in h1_values if str(item or "").strip()), "")
    except Exception:  # noqa: BLE001
        title = ""
    if not title:
        try:
            title = str(page.title() or "").strip()
        except Exception:  # noqa: BLE001
            title = ""
    title = re.sub(r"\s*\|\s*Shopee Brasil\s*$", "", title, flags=re.IGNORECASE).strip()

    image_candidates: list[str] = []
    try:
        image_candidates = page.eval_on_selector_all(
            "img",
            """els => els.map((element) => (
                element.currentSrc ||
                element.getAttribute('src') ||
                element.getAttribute('data-src') ||
                ''
            )).filter(Boolean)""",
        )
    except Exception:  # noqa: BLE001
        image_candidates = []
    image_urls = _dedupe_media_urls(
        [
            _normalize_shopee_image_candidate(url)
            for url in image_candidates
            if _is_shopee_gallery_image(url)
        ]
    )

    video_candidates: list[str] = []
    try:
        video_candidates = page.eval_on_selector_all(
            "video, source",
            """els => els.map((element) => (
                element.currentSrc ||
                element.getAttribute('src') ||
                ''
            )).filter(Boolean)""",
        )
    except Exception:  # noqa: BLE001
        video_candidates = []
    video_urls = _prioritize_reachable_video_urls([_clean_media_url(url) for url in video_candidates])

    tags = ["shopee", "manual"]
    if video_urls:
        encoded_video = urlsafe_b64encode(video_urls[0].encode("utf-8")).decode("ascii").rstrip("=")
        tags.append(f"shopee_video_url:{encoded_video}")

    return {
        "title": title,
        "description": f"Oferta Shopee importada manualmente de {source_url}",
        "price": 0.0,
        "old_price": None,
        "url": final_url,
        "canonical_url": final_url,
        "image": image_urls[0] if image_urls else "",
        "image_urls": image_urls,
        "category": infer_category_label(title, "", source_url, final_url),
        "tags": ",".join(tags),
        "featured": 0,
        "coupon": None,
        "affiliate_tag": os.getenv("SHOPEE_AFFILIATE_TAG", "").strip(),
        "video_url": video_urls[0] if video_urls else None,
        "video_urls": video_urls,
    }


def _extract_image_urls_from_html(html_text: str) -> list[str]:
    patterns = [
        r'"images"\s*:\s*\[([^\]]+)\]',
        r'"image"\s*:\s*\[([^\]]+)\]',
        r'"imageList"\s*:\s*\[([^\]]+)\]',
        r'"image_list"\s*:\s*\[([^\]]+)\]',
        r'"imageUrlList"\s*:\s*\[([^\]]+)\]',
        r'"image_url_list"\s*:\s*\[([^\]]+)\]',
        r'"thumbnailList"\s*:\s*\[([^\]]+)\]',
        r'"thumbnail_list"\s*:\s*\[([^\]]+)\]',
    ]
    single_patterns = [
        r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)["\']',
        r'"imageUrl"\s*:\s*"([^"]+)"',
        r'"image_url"\s*:\s*"([^"]+)"',
        r'"thumbnailUrl"\s*:\s*"([^"]+)"',
        r'"thumbnail_url"\s*:\s*"([^"]+)"',
        r'"@type":"Product".*?"image":"([^"]+)"',
    ]

    urls: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, html_text, re.IGNORECASE | re.DOTALL):
            inner_matches = re.findall(r'"([^"]+)"', str(match or ""))
            urls.extend(_normalize_shopee_image_candidate(item) for item in inner_matches)

    for pattern in single_patterns:
        for match in re.findall(pattern, html_text, re.IGNORECASE | re.DOTALL):
            urls.append(_normalize_shopee_image_candidate(str(match or "")))

    filtered = [url for url in urls if _is_shopee_gallery_image(url)]
    prioritized = [
        url
        for url in filtered
        if any(token in url.lower() for token in ("/file/", "susercontent", "cf.shopee"))
    ]
    fallback = [url for url in filtered if url not in prioritized]
    return _dedupe_media_urls(prioritized + fallback)


def _playwright_fallback_enabled() -> bool:
    _reload_shopee_env()
    value = (os.getenv("SHOPEE_BROWSER_FALLBACK_ENABLED") or "false").strip().lower()
    enabled = value in {"1", "true", "on", "yes", "sim"}
    if not enabled:
        return False
    if os.name != "nt":
        force_value = (os.getenv("SHOPEE_BROWSER_FALLBACK_FORCE") or "false").strip().lower()
        if force_value not in {"1", "true", "on", "yes", "sim"}:
            return False
    return True


def _playwright_fallback_timeout_ms() -> int:
    _reload_shopee_env()
    raw = (os.getenv("SHOPEE_BROWSER_FALLBACK_TIMEOUT_MS") or "45000").strip() or "45000"
    try:
        parsed = int(raw)
    except ValueError:
        return 45000
    return max(10000, min(parsed, 120000))


def _merge_offer_media(base_offer: dict[str, Any], fallback_offer: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base_offer)
    merged_images = _dedupe_media_urls(
        list(base_offer.get("image_urls") or [])
        + list(fallback_offer.get("image_urls") or [])
        + ([str(base_offer.get("image") or "").strip()] if base_offer.get("image") else [])
        + ([str(fallback_offer.get("image") or "").strip()] if fallback_offer.get("image") else [])
    )
    merged_videos = _prioritize_reachable_video_urls(
        list(base_offer.get("video_urls") or [])
        + list(fallback_offer.get("video_urls") or [])
        + ([str(base_offer.get("video_url") or "").strip()] if base_offer.get("video_url") else [])
        + ([str(fallback_offer.get("video_url") or "").strip()] if fallback_offer.get("video_url") else [])
    )

    if merged_images:
        merged["image_urls"] = merged_images
        merged["image"] = merged_images[0]
    if merged_videos:
        merged["video_urls"] = merged_videos
        merged["video_url"] = merged_videos[0]
        tags = [part.strip() for part in str(merged.get("tags") or "").split(",") if part.strip()]
        if not any(tag.startswith("shopee_video_url:") for tag in tags):
            encoded_video = urlsafe_b64encode(merged_videos[0].encode("utf-8")).decode("ascii").rstrip("=")
            tags.append(f"shopee_video_url:{encoded_video}")
            merged["tags"] = ",".join(dict.fromkeys(tags))

    if (len(merged_images) > 1 or merged_videos) and fallback_offer.get("canonical_url"):
        merged["canonical_url"] = _unwrap_shopee_login_redirect(str(fallback_offer["canonical_url"]))
    return merged


def _render_offer_via_browser(source_url: str) -> dict[str, Any] | None:
    if sync_playwright is None or not _playwright_fallback_enabled():
        return None

    timeout_ms = _playwright_fallback_timeout_ms()
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 2200},
                locale="pt-BR",
                user_agent=_build_browser_headers()["User-Agent"],
            )
            page = context.new_page()
            try:
                page.goto(source_url, wait_until="domcontentloaded", timeout=timeout_ms)
                page.wait_for_timeout(9000)
                final_url = str(page.url or source_url)
                dom_offer = _extract_browser_dom_offer(page, source_url)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:  # noqa: BLE001
                    pass
                try:
                    html_text = page.content()
                except Exception:  # noqa: BLE001
                    html_text = ""
                if not html_text or len(html_text) < 2000:
                    return dom_offer if dom_offer.get("title") or dom_offer.get("image_urls") else None
                try:
                    parsed_offer = _manual_offer_from_html(source_url, final_url, html_text)
                except Exception:  # noqa: BLE001
                    parsed_offer = {}
                if parsed_offer:
                    return _merge_offer_media(parsed_offer, dom_offer)
                return dom_offer if dom_offer.get("title") or dom_offer.get("image_urls") else None
            finally:
                context.close()
                browser.close()
    except (PlaywrightTimeoutError, ValueError):
        return None
    except Exception:  # noqa: BLE001
        return None


def _extract_video_urls_from_html(html_text: str) -> list[str]:
    patterns = [
        r'"videoUrl"\s*:\s*"([^"]+)"',
        r'"video_url"\s*:\s*"([^"]+)"',
        r'"play_url"\s*:\s*"([^"]+)"',
        r'"playUrl"\s*:\s*"([^"]+)"',
        r'"video_url_list"\s*:\s*\[([^\]]+)\]',
        r'"videoUrlList"\s*:\s*\[([^\]]+)\]',
        r'"video"\s*:\s*\{.*?"url"\s*:\s*"([^"]+)"',
    ]

    urls: list[str] = []
    for pattern in patterns:
        for match in re.findall(pattern, html_text, re.IGNORECASE | re.DOTALL):
            if pattern.endswith(r"\[([^\]]+)\]"):
                inner_matches = re.findall(r'"([^"]+)"', str(match or ""))
                urls.extend(_clean_media_url(item) for item in inner_matches)
                continue
            urls.append(_clean_media_url(str(match or "")))

    return _dedupe_media_urls(urls)


def _clean_coupon_text(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    text = re.sub(r"\s+", " ", text).strip(" -:")
    if len(text) < 3:
        return None
    return text[:80]


def _extract_coupon_from_payload(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_normalized = str(key or "").strip().lower()
            if any(token in key_normalized for token in ("coupon", "cupom", "voucher")):
                if isinstance(value, str):
                    cleaned = _clean_coupon_text(value)
                    if cleaned:
                        return cleaned
                if isinstance(value, (list, tuple)):
                    for entry in value:
                        cleaned = _clean_coupon_text(entry)
                        if cleaned:
                            return cleaned
                if isinstance(value, dict):
                    nested = _extract_coupon_from_payload(value)
                    if nested:
                        return nested
            if isinstance(value, (dict, list, tuple)):
                nested = _extract_coupon_from_payload(value)
                if nested:
                    return nested
    elif isinstance(payload, (list, tuple)):
        for entry in payload:
            nested = _extract_coupon_from_payload(entry)
            if nested:
                return nested
    return None


def _shopee_credentials() -> tuple[str, str]:
    _reload_shopee_env()
    credential = (
        os.getenv("SHOPEE_API_KEY", "").strip()
        or os.getenv("SHOPEE_APP_ID", "").strip()
        or os.getenv("SHOPEE_PARTNER_ID", "").strip()
    )
    secret = os.getenv("SHOPEE_API_SECRET", "").strip() or os.getenv("SHOPEE_SECRET_KEY", "").strip()
    return credential, secret


def _shopee_retry_hint_from_headers(headers: Any) -> tuple[int | None, str]:
    retry_after_seconds: int | None = None
    retry_after_raw = str((headers.get("Retry-After") if headers else "") or "").strip()
    if retry_after_raw.isdigit():
        retry_after_seconds = max(0, int(retry_after_raw))

    if retry_after_seconds is None:
        for header_name in ("X-RateLimit-Reset", "x-ratelimit-reset", "X-Reset-At"):
            raw_value = str((headers.get(header_name) if headers else "") or "").strip()
            if not raw_value:
                continue
            try:
                numeric_value = float(raw_value)
            except ValueError:
                continue
            if numeric_value > 10_000_000_000:
                numeric_value /= 1000.0
            now_value = time.time()
            if numeric_value > now_value:
                retry_after_seconds = max(0, int(numeric_value - now_value))
                break

    if retry_after_seconds is None:
        return None, "A Shopee nao informou quando o bloqueio termina."

    if retry_after_seconds <= 0:
        return 0, "A Shopee sinalizou bloqueio temporario, mas sem espera adicional."

    blocked_until = datetime.now(timezone.utc) + timedelta(seconds=retry_after_seconds)
    local_until = blocked_until.astimezone()
    if retry_after_seconds < 120:
        wait_label = f"em cerca de {retry_after_seconds} segundo(s)"
    else:
        wait_label = f"em cerca de {max(1, round(retry_after_seconds / 60))} minuto(s)"
    return retry_after_seconds, f"Tente novamente {wait_label} ({local_until.strftime('%d/%m %H:%M')})."


def _raise_shopee_temporarily_blocked(source: str, *, status_code: int | None = None, headers: Any = None, body: str = "") -> None:
    retry_after_seconds, retry_hint = _shopee_retry_hint_from_headers(headers or {})
    status_suffix = f" HTTP {int(status_code)}." if status_code else "."
    body_lower = str(body or "").lower()
    if "captcha" in body_lower or "challenge" in body_lower:
        source_label = "pagina da Shopee"
    elif source == "api":
        source_label = "API da Shopee"
    else:
        source_label = "Shopee"
    raise ShopeeBlockedError(
        f"{source_label} bloqueou temporariamente a leitura de produtos/midia.{status_suffix} {retry_hint}".strip(),
        source=source,
        retry_after_seconds=retry_after_seconds,
    )


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


def _normalize_manual_link(link: str) -> str:
    raw = (link or "").strip()
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        normalized = raw
    else:
        normalized = f"https://{raw.lstrip('/')}"
    return _unwrap_shopee_login_redirect(normalized)


def _unwrap_shopee_login_redirect(url: str) -> str:
    raw = str(url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if "shopee." not in host:
        return raw
    if "/buyer/login" not in path and "/portal/login" not in path:
        return raw

    query = parse_qs(parsed.query or "", keep_blank_values=False)
    candidates = query.get("next") or query.get("redirect") or []
    for candidate in candidates:
        normalized = str(candidate or "").strip()
        if not normalized:
            continue
        if normalized.startswith("/"):
            normalized = f"https://{host}{normalized}"
        if normalized.startswith("http://") or normalized.startswith("https://"):
            return normalized
    return raw


def _is_shopee_short_url(url: str) -> bool:
    host = (urlparse((url or "").strip()).netloc or "").lower()
    return host.startswith("s.shopee.")


def _build_browser_headers() -> dict[str, str]:
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


def _build_crawler_headers() -> dict[str, str]:
    return {
        "User-Agent": "facebookexternalhit/1.1 (+http://www.facebook.com/externalhit_uatext.php)",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
    }


def _manual_offer_from_html(source_url: str, final_url: str, html_text: str) -> dict[str, Any]:
    title = _extract_first(
        html_text,
        [
            r"<title[^>]*>(.*?)</title>",
            r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']twitter:title["\'][^>]+content=["\']([^"\']+)["\']',
            r'"@type":"Product","name":"([^"]+)"',
        ],
    )
    title = re.sub(r"\s*\|\s*Shopee Brasil\s*$", "", title, flags=re.IGNORECASE).strip()
    image_urls = _extract_image_urls_from_html(html_text)
    image = image_urls[0] if image_urls else ""
    description = _extract_first(
        html_text,
        [
            r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']',
            r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
            r'"@type":"Product","name":"[^"]+","description":"([^"]+)"',
        ],
    )
    trusted_price_text = _extract_first(
        html_text,
        [
            r'"price"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'"price_min"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'"priceMin"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'property=["\']product:price:amount["\'][^>]+content=["\']([\d\.,]+)["\']',
        ],
    )
    old_price_text = _extract_first(
        html_text,
        [
            r'"price_before_discount"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'"price_max_before_discount"\s*:\s*"?(\\?[\d\.,]+)"?',
            r'"priceBeforeDiscount"\s*:\s*"?(\\?[\d\.,]+)"?',
        ],
    )
    coupon_text = _extract_first(
        html_text,
        [
            r'"voucher_code"\s*:\s*"([^"]+)"',
            r'"coupon_code"\s*:\s*"([^"]+)"',
            r'"voucherCode"\s*:\s*"([^"]+)"',
            r'"couponCode"\s*:\s*"([^"]+)"',
            r'Cupom[:\s]+([A-Z0-9_-]{3,})',
            r'Voucher[:\s]+([A-Z0-9_-]{3,})',
        ],
    )
    video_urls = _prioritize_reachable_video_urls(_extract_video_urls_from_html(html_text))
    tags = ["shopee", "manual"]
    if video_urls:
        encoded_video = urlsafe_b64encode(video_urls[0].encode("utf-8")).decode("ascii").rstrip("=")
        tags.append(f"shopee_video_url:{encoded_video}")

    final_host = (urlparse(final_url).netloc or "").lower()
    if "shopee" not in final_host:
        raise ValueError("O link informado nao redirecionou para uma pagina valida da Shopee.")
    if not title:
        raise ValueError("Nao foi possivel extrair o titulo do produto da pagina da Shopee.")

    price = _normalize_price(trusted_price_text) if trusted_price_text else 0.0
    old_price = _normalize_price(old_price_text) if old_price_text else None

    if price <= 0:
        visible_prices = [
            _normalize_price(value)
            for value in _extract_all(
                html_text,
                [
                    r'R\$\s*([\d\.,]+)',
                    r'"price"\s*:\s*"?(\\?[\d\.,]+)"?',
                    r'"price_min"\s*:\s*"?(\\?[\d\.,]+)"?',
                    r'"priceMin"\s*:\s*"?(\\?[\d\.,]+)"?',
                ],
            )
        ]
        visible_prices = [value for value in visible_prices if value > 0]
        if visible_prices:
            price = min(visible_prices)
            if old_price is None:
                higher_prices = [value for value in visible_prices if value > price]
                old_price = max(higher_prices) if higher_prices else None

    return {
        "title": title,
        "description": description or f"Oferta Shopee importada manualmente de {source_url}",
        "price": price,
        "old_price": old_price if old_price and old_price > price else None,
        "url": final_url or source_url,
        "canonical_url": final_url or source_url,
        "image": image,
        "image_urls": image_urls,
        "category": infer_category_label(title, description, source_url, final_url),
        "tags": ",".join(tags),
        "featured": 0,
        "coupon": _clean_coupon_text(coupon_text),
        "affiliate_tag": os.getenv("SHOPEE_AFFILIATE_TAG", "").strip(),
        "video_url": video_urls[0] if video_urls else None,
        "video_urls": video_urls,
    }


def preview_shopee_affiliate_links(links: list[str]) -> list[dict[str, Any]]:
    cleaned_links = [item for item in (_normalize_manual_link(link) for link in links) if item]
    if not cleaned_links:
        raise ValueError("Cole pelo menos um link da Shopee.")

    offers: list[dict[str, Any]] = []
    for link in cleaned_links:
        last_error: Exception | None = None
        candidates: list[dict[str, Any]] = []
        resolved_affiliate_url = ""
        link_candidates = [link]
        extracted_ids = _extract_shopee_ids_from_url(link)
        if extracted_ids:
            canonical_candidate = _build_shopee_product_url(extracted_ids[0], extracted_ids[1])
            if canonical_candidate and canonical_candidate not in link_candidates:
                link_candidates.append(canonical_candidate)

        for candidate_link in link_candidates:
            candidate_success = False
            for headers in (_build_crawler_headers(), _build_browser_headers()):
                try:
                    with httpx.Client(timeout=25, headers=headers, follow_redirects=True) as client:
                        response = client.get(candidate_link)
                        if response.status_code in {403, 429}:
                            _raise_shopee_temporarily_blocked("page", status_code=response.status_code, headers=response.headers, body=response.text)
                        response.raise_for_status()
                        response_url = _unwrap_shopee_login_redirect(str(response.url))
                        if response_url and not _is_shopee_short_url(response_url):
                            resolved_affiliate_url = response_url
                        content_type = (response.headers.get("content-type") or "").lower()
                        if "text/html" not in content_type and "application/xhtml" not in content_type:
                            raise ValueError("A Shopee retornou um formato inesperado para o link informado.")
                        lowered_body = response.text.lower()
                        if any(token in lowered_body for token in ("captcha", "access denied", "too many requests", "sec challenge", "verify you are human")):
                            _raise_shopee_temporarily_blocked("page", headers=response.headers, body=response.text)
                        candidates.append(_manual_offer_from_html(candidate_link, response_url, response.text))
                        last_error = None
                        candidate_success = True
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
            if candidate_success:
                break
        if candidates:
            candidates.sort(
                key=lambda item: (
                    1 if float(item.get("price") or 0) > 0 else 0,
                    1 if not _is_shopee_short_url(item.get("canonical_url") or "") else 0,
                    1 if "utm_medium=affiliates" in str(item.get("url") or "").lower() else 0,
                ),
                reverse=True,
            )
            selected = dict(candidates[0])
            if len(selected.get("image_urls") or []) <= 1 or not (selected.get("video_urls") or []):
                browser_offer = _render_offer_via_browser(resolved_affiliate_url or link)
                if browser_offer:
                    selected = _merge_offer_media(selected, browser_offer)
            if resolved_affiliate_url:
                selected["url"] = resolved_affiliate_url
                if _is_shopee_short_url(selected.get("canonical_url") or ""):
                    selected["canonical_url"] = resolved_affiliate_url
            offers.append(selected)
            continue
        if last_error is not None:
            raise last_error

    return offers


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
                "image_urls": item.get("image_urls") or ([item.get("image")] if item.get("image") else []),
                "video_urls": item.get("video_urls") or ([item.get("video_url")] if item.get("video_url") else []),
                "category": item.get("category") or infer_category_label(item.get("title"), item.get("description"), item.get("url")),
                "tags": item.get("tags", "shopee"),
                "featured": int(item.get("featured", 0)),
                "coupon": _extract_coupon_from_payload(item),
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
    rating_star = _safe_float(node.get("ratingStar"))
    price_discount_rate = _safe_int(node.get("priceDiscountRate"))
    shop_name = (node.get("shopName") or "").strip()
    sales = _safe_int(node.get("sales"))
    category = infer_category_label(
        keyword,
        node.get("productName") or "",
        node.get("productLink") or "",
        node.get("offerLink") or "",
        shop_name,
    )

    tags = ["shopee", keyword]
    if shop_name:
        tags.append(shop_name.lower().replace(" ", "-"))
    if commission_rate is not None:
        tags.append(f"commission:{commission_rate}")
    if sales > 0:
        tags.append(f"sold:{sales}")

    image_url = node.get("imageUrl") or node.get("image") or ""
    image_urls = [
        _clean_media_url(str(value))
        for value in (
            node.get("imageUrlList")
            or node.get("image_url_list")
            or node.get("images")
            or ([image_url] if image_url else [])
        )
        if _clean_media_url(str(value))
    ]

    return {
        "title": node.get("productName") or node.get("title") or "Oferta Shopee",
        "description": f"Oferta Shopee encontrada para: {keyword}",
        "price": price,
        "old_price": old_price if old_price and old_price > price else None,
        "url": node.get("offerLink") or node.get("productLink") or "#",
        "image": image_url,
        "image_urls": _dedupe_media_urls(image_urls),
        "category": category,
        "tags": ",".join(dict.fromkeys(tags)),
        "featured": 0,
        "coupon": _extract_coupon_from_payload(node),
        "affiliate_tag": affiliate_tag,
        "product_id": str(node.get("productId") or node.get("itemId") or "") or None,
        "item_id": str(node.get("itemId") or node.get("productId") or "") or None,
        "shop_id": str(node.get("shopId") or "") or None,
        "sales": sales,
        "commission_rate": commission_rate,
        "rating_star": rating_star,
        "price_discount_rate": price_discount_rate,
    }


def _fetch_graphql_offer_page(
    client: httpx.Client,
    *,
    keyword: str,
    page: int,
    limit: int,
    sort_type: int,
    credential: str,
    secret: str,
    affiliate_tag: str,
    api_url: str,
    query: str,
) -> list[dict[str, Any]]:
    variables = _build_graphql_variables(keyword, page, limit, sort_type)
    body = {"query": query, "variables": variables}
    payload = json.dumps(body, separators=(",", ":"), ensure_ascii=False)
    headers = _build_auth_headers(credential, secret, payload)

    response = client.post(api_url, content=payload.encode("utf-8"), headers=headers)
    if response.status_code in {403, 429}:
        _raise_shopee_temporarily_blocked("api", status_code=response.status_code, headers=response.headers, body=response.text)
    response.raise_for_status()
    data = response.json()

    for error in data.get("errors", []) or []:
        message = error.get("message") if isinstance(error, dict) else str(error)
        lowered = message.lower()
        if any(token in lowered for token in ("rate limit", "too many requests", "throttle", "captcha", "temporar")):
            _raise_shopee_temporarily_blocked("api", headers=response.headers, body=message)
        if "open api" in lowered or "access" in lowered or "permission" in lowered or "unauthorized" in lowered:
            raise ValueError(
                "Sua conta Shopee ainda nao tem acesso liberado para a Open API de Afiliados. "
                "Assim que AppID e Secret forem aprovados, este coletor fica pronto para uso."
            )
        raise ValueError(f"Shopee GraphQL error: {message}")

    nodes = _extract_nodes(data)
    return [_node_to_offer(node, keyword, affiliate_tag) for node in nodes]


def _fetch_api_offers(keyword_override: str | None = None, page_override: int | None = None, limit_override: int | None = None) -> list[dict[str, Any]]:
    credential, secret = _shopee_credentials()
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
                page_offers = _fetch_graphql_offer_page(
                    client,
                    keyword=keyword,
                    page=page,
                    limit=limit,
                    sort_type=sort_type,
                    credential=credential,
                    secret=secret,
                    affiliate_tag=affiliate_tag,
                    api_url=api_url,
                    query=query,
                )
                if not page_offers:
                    break

                for offer in page_offers:
                    url = offer.get("url", "#")
                    if not url or url == "#" or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    offers.append(offer)

    offers.sort(
        key=lambda offer: (
            _safe_int(offer.get("sales"), 0),
            _safe_float(offer.get("commission_rate")) or 0.0,
            _safe_int(offer.get("price_discount_rate"), 0),
            _safe_float(offer.get("rating_star")) or 0.0,
        ),
        reverse=True,
    )
    return offers


def _enrich_offer_with_media(base_offer: dict[str, Any]) -> dict[str, Any]:
    candidate_urls: list[str] = []
    direct_product_url = _build_shopee_product_url(
        base_offer.get("shop_id"),
        base_offer.get("item_id") or base_offer.get("product_id"),
    )
    if direct_product_url:
        candidate_urls.append(direct_product_url)

    for raw_url in (
        base_offer.get("canonical_url"),
        base_offer.get("url"),
    ):
        cleaned = str(raw_url or "").strip()
        if not cleaned:
            continue
        candidate_urls.append(cleaned)
        extracted_ids = _extract_shopee_ids_from_url(cleaned)
        if extracted_ids:
            canonical_candidate = _build_shopee_product_url(extracted_ids[0], extracted_ids[1])
            if canonical_candidate:
                candidate_urls.append(canonical_candidate)

    deduped_candidates: list[str] = []
    seen_urls: set[str] = set()
    for candidate_url in candidate_urls:
        if not candidate_url or candidate_url in seen_urls:
            continue
        seen_urls.add(candidate_url)
        deduped_candidates.append(candidate_url)

    if not deduped_candidates:
        return base_offer

    best_offer = dict(base_offer)
    best_score = _offer_media_score(best_offer)
    for candidate_url in deduped_candidates:
        try:
            enriched_offer = preview_shopee_affiliate_links([candidate_url])[0]
        except Exception:  # noqa: BLE001
            continue

        merged_offer = _merge_offer_media(base_offer, enriched_offer)
        if not merged_offer.get("canonical_url") and enriched_offer.get("canonical_url"):
            merged_offer["canonical_url"] = enriched_offer["canonical_url"]
        merged_score = _offer_media_score(merged_offer)
        if merged_score > best_score:
            best_offer = merged_offer
            best_score = merged_score

    return best_offer


def enrich_shopee_offers_with_media(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    for offer in offers:
        enriched.append(_enrich_offer_with_media(offer))
    return enriched


def _lookup_keyword_candidates(base_offer: dict[str, Any]) -> list[str]:
    raw_title = re.sub(r"\s+", " ", str(base_offer.get("title") or "").strip())
    if not raw_title:
        return []

    ascii_title = "".join(
        char for char in unicodedata.normalize("NFKD", raw_title)
        if not unicodedata.combining(char)
    )

    candidates: list[str] = [raw_title, ascii_title]
    words = [part for part in raw_title.split(" ") if part]
    ascii_words = [part for part in ascii_title.split(" ") if part]
    for size in (8, 5, 4, 3):
        if len(words) >= size:
            candidates.append(" ".join(words[:size]))
        if len(ascii_words) >= size:
            candidates.append(" ".join(ascii_words[:size]))

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = candidate.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _match_offer_by_ids(candidate: dict[str, Any], expected_shop_id: str, expected_item_id: str) -> bool:
    candidate_shop_id = str(candidate.get("shop_id") or "").strip()
    candidate_item_id = str(candidate.get("item_id") or candidate.get("product_id") or "").strip()
    if not candidate_item_id:
        return False
    if expected_item_id and candidate_item_id != expected_item_id:
        return False
    if expected_shop_id and candidate_shop_id and candidate_shop_id != expected_shop_id:
        return False
    return True


def lookup_shopee_offer_via_api(base_offer: dict[str, Any], *, page_limit: int = 5, per_page_limit: int = 50) -> dict[str, Any] | None:
    credential, secret = _shopee_credentials()
    if not credential or not secret:
        return None

    extracted_ids = (
        _extract_shopee_ids_from_url(str(base_offer.get("canonical_url") or "").strip())
        or _extract_shopee_ids_from_url(str(base_offer.get("url") or "").strip())
    )
    expected_shop_id = str(base_offer.get("shop_id") or (extracted_ids[0] if extracted_ids else "") or "").strip()
    expected_item_id = str(base_offer.get("item_id") or base_offer.get("product_id") or (extracted_ids[1] if extracted_ids else "") or "").strip()
    if not expected_item_id:
        return None

    keyword_candidates = _lookup_keyword_candidates(base_offer)
    if not keyword_candidates:
        return None

    affiliate_tag = os.getenv("SHOPEE_AFFILIATE_TAG", "").strip()
    api_url = os.getenv("SHOPEE_API_URL", SHOPEE_API_URL).strip() or SHOPEE_API_URL
    sort_type = _safe_int(os.getenv("SHOPEE_SORT_TYPE", "1"), 1)
    timeout = max(5, _safe_int(os.getenv("SHOPEE_TIMEOUT", "20"), 20))
    query = _build_graphql_query()
    per_page_limit = max(10, min(int(per_page_limit or 50), 50))
    page_limit = max(1, min(int(page_limit or 5), 10))

    with httpx.Client(timeout=timeout) as client:
        for keyword in keyword_candidates:
            for page in range(1, page_limit + 1):
                try:
                    page_offers = _fetch_graphql_offer_page(
                        client,
                        keyword=keyword,
                        page=page,
                        limit=per_page_limit,
                        sort_type=sort_type,
                        credential=credential,
                        secret=secret,
                        affiliate_tag=affiliate_tag,
                        api_url=api_url,
                        query=query,
                    )
                except Exception:  # noqa: BLE001
                    break

                if not page_offers:
                    break

                for candidate in page_offers:
                    if _match_offer_by_ids(candidate, expected_shop_id, expected_item_id):
                        matched = dict(base_offer)
                        matched.update(candidate)
                        matched["store"] = "Shopee"
                        matched["provider"] = "shopee"
                        return matched

                if len(page_offers) < per_page_limit:
                    break

    return None


def resolve_shopee_offer_for_reimport(base_offer: dict[str, Any]) -> dict[str, Any]:
    seed_offer = dict(base_offer)
    api_offer = lookup_shopee_offer_via_api(seed_offer)
    if api_offer:
        seed_offer.update(api_offer)
    enriched_offer = _enrich_offer_with_media(seed_offer)
    merged_offer = dict(seed_offer)
    merged_offer.update(enriched_offer)
    merged_offer["store"] = "Shopee"
    merged_offer["provider"] = "shopee"
    return merged_offer


def fetch_shopee_offers(limit_override: int | None = None, enrich_media: bool = False, keyword_override: str | None = None) -> list[dict[str, Any]]:
    if _looks_like_shopee_product_url(str(keyword_override or "")):
        direct_items = preview_shopee_affiliate_links([str(keyword_override or "").strip()])
        if not direct_items:
            return []
        resolved_items: list[dict[str, Any]] = []
        for item in direct_items[: max(1, int(limit_override or 1))]:
            resolved = resolve_shopee_offer_for_reimport(item)
            resolved_items.append(resolved)
        return resolved_items

    api_offers = _fetch_api_offers(keyword_override=keyword_override, limit_override=limit_override)
    if api_offers:
        if limit_override is not None:
            api_offers = api_offers[: max(1, int(limit_override))]
        if enrich_media and api_offers:
            return enrich_shopee_offers_with_media(api_offers)
        return api_offers
    return _fetch_feed_offers()


def preview_shopee_offers(keyword: str, limit: int = 10, pages: int = 1) -> list[dict[str, Any]]:
    credential, secret = _shopee_credentials()
    if not credential or not secret:
        raise ValueError("Shopee API ainda nao configurada. Aguarde AppID/Secret liberados ou preencha as credenciais no .env.")
    return _fetch_api_offers(keyword_override=keyword, limit_override=limit, page_override=pages)


def search_shopee_offers_page(keyword: str, *, page: int = 1, limit: int = 12) -> dict[str, Any]:
    credential, secret = _shopee_credentials()
    if not credential or not secret:
        raise ValueError("Shopee API ainda nao configurada. Aguarde AppID/Secret liberados ou preencha as credenciais no .env.")

    normalized_keyword = (keyword or "").strip()
    if not normalized_keyword:
        raise ValueError("Informe um termo para pesquisar produtos da Shopee.")

    if _looks_like_shopee_product_url(normalized_keyword):
        direct_items = preview_shopee_affiliate_links([normalized_keyword])
        final_items: list[dict[str, Any]] = []
        for item in direct_items[:1]:
            resolved_item = resolve_shopee_offer_for_reimport(item)
            preview_item = dict(resolved_item)
            preview_item["url"] = str(resolved_item.get("affiliate_url") or resolved_item.get("url") or normalized_keyword).strip()
            preview_item["canonical_url"] = str(resolved_item.get("canonical_url") or item.get("canonical_url") or normalized_keyword).strip()
            preview_item.setdefault("sales", 0)
            preview_item.setdefault("commission_rate", 0)
            final_items.append(preview_item)
        return {
            "keyword": normalized_keyword,
            "page": 1,
            "limit": 1,
            "count": len(final_items),
            "has_more": False,
            "items": final_items,
        }

    page = max(1, int(page or 1))
    limit = max(1, min(int(limit or 12), 50))
    affiliate_tag = os.getenv("SHOPEE_AFFILIATE_TAG", "").strip()
    api_url = os.getenv("SHOPEE_API_URL", SHOPEE_API_URL).strip() or SHOPEE_API_URL
    sort_type = _safe_int(os.getenv("SHOPEE_SORT_TYPE", "1"), 1)
    timeout = max(5, _safe_int(os.getenv("SHOPEE_TIMEOUT", "20"), 20))
    query = _build_graphql_query()

    with httpx.Client(timeout=timeout) as client:
        items = _fetch_graphql_offer_page(
            client,
            keyword=normalized_keyword,
            page=page,
            limit=limit,
            sort_type=sort_type,
            credential=credential,
            secret=secret,
            affiliate_tag=affiliate_tag,
            api_url=api_url,
            query=query,
        )

    items.sort(
        key=lambda offer: (
            _safe_int(offer.get("sales"), 0),
            _safe_float(offer.get("commission_rate")) or 0.0,
            _safe_int(offer.get("price_discount_rate"), 0),
            _safe_float(offer.get("rating_star")) or 0.0,
        ),
        reverse=True,
    )
    return {
        "keyword": normalized_keyword,
        "page": page,
        "limit": limit,
        "count": len(items),
        "has_more": len(items) >= limit,
        "items": items,
    }
