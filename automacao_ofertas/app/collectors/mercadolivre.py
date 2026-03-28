import csv
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

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


def _optional_positive_int_env(name: str, default: int) -> int | None:
    raw = (os.getenv(name) or "").strip()
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    if value <= 0:
        return None
    return value


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
            if "coupon" in key_normalized or "cupom" in key_normalized:
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


def _extract_meli_item_id(url: str) -> str | None:
    parsed = urlparse((url or "").strip())
    for values in (
        parse_qs(parsed.query, keep_blank_values=True),
        parse_qs(parsed.fragment, keep_blank_values=True),
    ):
        for key in ("wid", "item_id", "item"):
            candidate = str((values.get(key) or [None])[0] or "").strip().upper().replace("-", "")
            match = re.search(r"(MLB)(\d+)", candidate)
            if match:
                return f"{match.group(1)}{match.group(2)}"
    match = re.search(r"(MLB)[-_]?(\d+)", parsed.path, re.IGNORECASE)
    if not match:
        return None
    return f"{match.group(1).upper()}{match.group(2)}"


def _extract_meli_product_id(url: str) -> str | None:
    match = re.search(r"/p/(MLB\d+)", unquote((url or "").strip()), re.IGNORECASE)
    return match.group(1).upper() if match else None


def _extract_social_profile_product_links(html_text: str, limit: int = 120) -> list[str]:
    patterns = [
        r'https://[^"\']*mercadolivre\.com\.br/[^"\']+',
        r'https://[^"\']*mercadolibre\.com/[^"\']+',
        r'https:\\/\\/[^"\']*mercadolivre\.com\.br\\/[^"\']+',
        r'https:\\/\\/[^"\']*mercadolibre\.com\\/[^"\']+',
    ]
    links: list[str] = []
    seen: set[str] = set()
    for pattern in patterns:
        for raw_match in re.findall(pattern, html_text or "", re.IGNORECASE):
            url = (
                str(raw_match or "")
                .replace("\\/", "/")
                .replace("\\u0026", "&")
                .replace("\\u003d", "=")
                .replace("&amp;", "&")
                .strip()
            )
            lowered = url.lower()
            if not url.startswith("https://"):
                continue
            if "/p/mlb" not in lowered or "wid=" not in lowered:
                continue
            if url in seen:
                continue
            seen.add(url)
            links.append(url)
            if len(links) >= limit:
                return links
    return links


def _shipping_summary_from_item(item: dict[str, Any]) -> str | None:
    shipping = item.get("shipping")
    if not isinstance(shipping, dict):
        return None
    parts: list[str] = []
    if bool(shipping.get("free_shipping")):
        parts.append("Frete gratis")
    logistic_type = str(shipping.get("logistic_type") or "").strip().replace("_", " ")
    if logistic_type:
        parts.append(logistic_type)
    return " | ".join(parts) or None


def _fetch_offer_details_from_affiliate_url(
    client: httpx.Client,
    affiliate_url: str,
    access_token: str = "",
) -> dict[str, Any] | None:
    item_id = _extract_meli_item_id(affiliate_url)
    product_id = _extract_meli_product_id(affiliate_url)
    if not item_id and not product_id:
        return None

    item_payload: dict[str, Any] = {}
    headers = _build_auth_headers(access_token) if access_token else {}

    if product_id and headers:
        try:
            product_response = client.get(f"{MELI_API_URL}/products/{product_id}", headers=headers)
            product_response.raise_for_status()
            product_payload = product_response.json()

            product_items_response = client.get(
                f"{MELI_API_URL}/products/{product_id}/items",
                headers=headers,
                params={"limit": 1},
            )
            product_items_response.raise_for_status()
            product_items = product_items_response.json().get("results", [])
            if product_items:
                item_payload = product_items[0]

            title = str(product_payload.get("name") or product_payload.get("family_name") or "").strip()
            image_url = ""
            pictures = product_payload.get("pictures") or []
            if isinstance(pictures, list) and pictures:
                image_url = str((pictures[0] or {}).get("url") or "").strip()
            if not image_url:
                picker_groups = product_payload.get("pickers") or []
                for picker in picker_groups:
                    picker_products = (picker or {}).get("products") or []
                    if picker_products:
                        image_url = str((picker_products[0] or {}).get("thumbnail") or "").strip()
                        if image_url:
                            break

            price = _safe_float(item_payload.get("price"), 0.0)
            if price > 0:
                return {
                    "title": title or "Oferta Mercado Livre",
                    "description": "Oferta importada automaticamente da pagina social oficial do Mercado Livre.",
                    "price": price,
                    "old_price": _safe_float(item_payload.get("original_price"), 0.0) or None,
                    "url": affiliate_url,
                    "image": image_url or str(item_payload.get("thumbnail") or "").strip(),
                    "category": str(item_payload.get("category_id") or product_payload.get("domain_id") or "ofertas"),
                    "tags": _tags_with_metadata("mercadolivre,social_profile_html", item_payload.get("sold_quantity")),
                    "featured": 1,
                    "sold_quantity": _safe_int(item_payload.get("sold_quantity"), 0),
                    "coupon": _extract_coupon_from_payload(item_payload),
                    "item_id": item_id or item_payload.get("item_id"),
                    "product_id": product_id or product_payload.get("id"),
                    "affiliate_tag": os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "").strip(),
                    "shipping": _shipping_summary_from_item(item_payload),
                    "promotion_text": None,
                }
        except Exception:
            pass

    if item_id:
        try:
            item_response = client.get(f"{MELI_API_URL}/items/{item_id}", headers=headers)
            item_response.raise_for_status()
            item_payload = item_response.json()
        except Exception:
            item_payload = {}

    title = ""
    title = str(item_payload.get("title") or "").strip()
    if not title and product_id:
        try:
            product_response = client.get(f"{MELI_API_URL}/products/{product_id}", headers=headers)
            product_response.raise_for_status()
            product_payload = product_response.json()
            title = str(product_payload.get("name") or product_payload.get("family_name") or "").strip()
        except Exception:
            title = ""

    price = _safe_float(item_payload.get("price"), 0.0)
    if price <= 0:
        return None

    old_price = _safe_float(item_payload.get("original_price"), 0.0) or None
    image_url = str(item_payload.get("thumbnail") or "").strip()
    if not image_url:
        pictures = item_payload.get("pictures") or []
        if isinstance(pictures, list) and pictures:
            image_url = str((pictures[0] or {}).get("url") or "").strip()

    return {
        "title": title or "Oferta Mercado Livre",
        "description": "Oferta importada automaticamente da pagina social oficial do Mercado Livre.",
        "price": price,
        "old_price": old_price,
        "url": affiliate_url,
        "image": image_url,
        "category": str(item_payload.get("category_id") or "ofertas"),
        "tags": _tags_with_metadata("mercadolivre,social_profile_html", item_payload.get("sold_quantity")),
        "featured": 1,
        "sold_quantity": _safe_int(item_payload.get("sold_quantity"), 0),
        "coupon": _extract_coupon_from_payload(item_payload),
        "item_id": item_id,
        "product_id": product_id or item_payload.get("catalog_product_id"),
        "affiliate_tag": os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "").strip(),
        "shipping": _shipping_summary_from_item(item_payload),
        "promotion_text": None,
    }


def _decode_embedded_text(value: str) -> str:
    return (
        str(value or "")
        .replace("\\u002F", "/")
        .replace("\\u0026", "&")
        .replace("\\u003D", "=")
        .replace("\\u002B", "+")
        .replace("\\u002D", "-")
        .replace("\\/", "/")
    )


def _is_meli_deep_social_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    if "mercadolivre.com.br" not in (parsed.netloc or "").lower():
        return False
    if not parsed.path.startswith("/social/"):
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    return bool((query.get("ref") or [None])[0])


def _extract_urls_from_binary_blob(data: bytes) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    def collect(text: str) -> None:
        for match in re.findall(r"https://[^\s\"'<>]+", text or "", re.IGNORECASE):
            cleaned = (
                str(match or "")
                .replace("\\u0026", "&")
                .replace("\\u003d", "=")
                .replace("&amp;", "&")
                .strip()
            )
            cleaned = re.split(r"[\x00-\x1f]+", cleaned, maxsplit=1)[0].strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                found.append(cleaned)

    collect(data.decode("utf-8", "ignore"))
    collect(data.decode("latin1", "ignore"))
    collect(data[0:].decode("utf-16le", "ignore"))
    collect(data[1:].decode("utf-16le", "ignore"))
    return found


def _resolve_meli_short_url(url: str, client: httpx.Client) -> str:
    target = (url or "").strip()
    if not target:
        return ""
    if urlparse(target).netloc.lower() != "meli.la":
        return target
    try:
        response = client.get(target, headers=_browser_headers(), follow_redirects=False)
        return str(response.headers.get("location") or "").strip() or target
    except Exception:
        return target


def _configured_browser_profile_names() -> list[str]:
    names: list[str] = []
    raw_profiles = os.getenv("MELI_BROWSER_SESSION_PROFILES", "").strip()
    if raw_profiles:
        names.extend(part.strip() for part in raw_profiles.split(",") if part.strip())

    legacy_profile = os.getenv("MELI_CHROME_SESSION_PROFILE", "").strip()
    if legacy_profile:
        names.append(legacy_profile)

    if not names:
        names.append("Default")

    deduped: list[str] = []
    seen: set[str] = set()
    for name in names:
        lowered = name.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(name)
    return deduped


def _configured_social_page_urls() -> list[str]:
    urls: list[str] = []

    raw_urls = os.getenv("MELI_SOCIAL_PAGE_URLS", "").strip()
    if raw_urls:
        urls.extend(part.strip() for part in raw_urls.split(",") if part.strip())

    legacy_url = os.getenv("MELI_SOCIAL_PAGE_URL", "").strip()
    if legacy_url:
        urls.append(legacy_url)

    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = url.strip()
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def _is_meli_social_list_url(url: str) -> bool:
    parsed = urlparse((url or "").strip())
    host = (parsed.netloc or "").lower()
    if "mercadolivre.com.br" not in host:
        return False
    return "/social/" in (parsed.path or "").lower() and "/lists/" in (parsed.path or "").lower()


def _expand_social_page_urls(url: str) -> list[str]:
    normalized = (url or "").strip()
    if not normalized:
        return []
    if not _is_meli_social_list_url(normalized):
        return [normalized]

    max_pages = max(1, _safe_int(os.getenv("MELI_SOCIAL_LIST_MAX_PAGES", "10"), 10))
    parsed = urlparse(normalized)
    base_query = parse_qs(parsed.query, keep_blank_values=True)
    expanded: list[str] = []
    for page in range(1, max_pages + 1):
        query = dict(base_query)
        query["page"] = [str(page)]
        page_url = urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                "",
                urlencode([(key, value) for key, values in query.items() for value in values]),
                "",
            )
        )
        expanded.append(page_url)
    return expanded


def _browser_user_data_roots() -> list[Path]:
    local_app_data = Path(os.getenv("LOCALAPPDATA", "")).expanduser()
    if not str(local_app_data):
        return []

    roots = [
        local_app_data / "Google" / "Chrome" / "User Data",
        local_app_data / "Microsoft" / "Edge" / "User Data",
    ]
    return [path for path in roots if path.is_dir()]


def _discover_browser_session_dirs() -> list[Path]:
    if os.name != "nt":
        return []

    configured_profiles = _configured_browser_profile_names()
    discovered: list[Path] = []
    seen: set[str] = set()

    def add_session_dir(path: Path) -> None:
        sessions_dir = path / "Sessions"
        if not sessions_dir.is_dir():
            return
        key = str(sessions_dir).lower()
        if key in seen:
            return
        seen.add(key)
        discovered.append(sessions_dir)

    for root in _browser_user_data_roots():
        for profile_name in configured_profiles:
            add_session_dir(root / profile_name)

    for root in _browser_user_data_roots():
        candidates = [
            child for child in root.iterdir()
            if child.is_dir() and (child / "Sessions").is_dir()
        ]
        candidates.sort(
            key=lambda child: (child / "Sessions").stat().st_mtime,
            reverse=True,
        )
        for child in candidates[:6]:
            add_session_dir(child)

    return discovered


def _load_browser_session_url_batches() -> list[list[str]]:
    session_dirs = _discover_browser_session_dirs()
    if not session_dirs:
        return []

    max_files = max(4, _safe_int(os.getenv("MELI_BROWSER_SESSION_MAX_FILES", "24"), 24))
    session_files: list[Path] = []
    for sessions_dir in session_dirs:
        files = [
            *sessions_dir.glob("Session_*"),
            *sessions_dir.glob("Tabs_*"),
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        session_files.extend(files[:6])

    session_files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    batches: list[list[str]] = []
    seen_files: set[str] = set()
    for session_path in session_files:
        key = str(session_path).lower()
        if key in seen_files:
            continue
        seen_files.add(key)
        if len(batches) >= max_files:
            break
        try:
            urls = _extract_urls_from_binary_blob(session_path.read_bytes())
        except OSError:
            continue
        if urls:
            batches.append(urls)
    return batches


def _resolve_social_url_from_chrome_sessions(
    affiliate_url: str,
    item_id: str,
    product_id: str,
    client: httpx.Client,
    session_url_batches: list[list[str]] | None = None,
) -> str:
    if os.name != "nt":
        return ""

    target_tokens = {
        token
        for token in [
            (item_id or "").strip().upper(),
            (product_id or "").strip().upper(),
            _extract_meli_item_id(affiliate_url) or "",
            _extract_meli_product_id(affiliate_url) or "",
        ]
        if token
    }
    target_path = urlparse(affiliate_url).path.strip().lower()
    if not target_tokens and not target_path:
        return ""

    batches = session_url_batches if session_url_batches is not None else _load_browser_session_url_batches()
    for urls in batches:
        for index, candidate in enumerate(urls):
            normalized_candidate = candidate.strip()
            candidate_upper = normalized_candidate.upper()
            try:
                candidate_path = urlparse(normalized_candidate).path.strip().lower()
            except ValueError:
                continue
            matched = any(token in candidate_upper for token in target_tokens)
            if not matched and not (target_path and candidate_path and candidate_path == target_path):
                continue

            nearby = urls[max(0, index - 3): min(len(urls), index + 4)]
            for nearby_url in nearby:
                resolved = _resolve_meli_short_url(nearby_url, client).strip()
                if _is_meli_deep_social_url(resolved):
                    return resolved

    return ""


def _compact_social_page_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return (url or "").strip()
    query = parse_qs(parsed.query, keep_blank_values=True)
    allowed: list[tuple[str, str]] = []
    for key in ("matt_word", "matt_tool", "forceInApp"):
        value = (query.get(key) or [None])[0]
        if value not in (None, ""):
            allowed.append((key, str(value)))
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", urlencode(allowed), ""))


def _fetch_social_profile_offers(client: httpx.Client, access_token: str = "") -> list[dict[str, Any]]:
    social_page_urls = _configured_social_page_urls()
    if not social_page_urls:
        return []

    limit = _optional_positive_int_env("MELI_SOCIAL_LIMIT", 80)
    offers: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    session_url_batches = _load_browser_session_url_batches()
    metadata_pattern = re.compile(
        r'"metadata":\{"id":"(MLB\d+)","product_id":"(MLB\d+)","user_product_id":"[^"]*","url":"([^"]+)","url_fragments":"([^"]*)","category_id":"([^"]*)","url_params":"([^"]*)"\}',
        re.IGNORECASE,
    )

    for configured_url in social_page_urls:
        for social_page_url in _expand_social_page_urls(configured_url):
            if limit is not None and len(offers) >= limit:
                break

            try:
                response = client.get(social_page_url, headers=_browser_headers(), follow_redirects=True)
                response.raise_for_status()
            except Exception:
                continue

            html_text = response.text
            html_product_links = _extract_social_profile_product_links(
                html_text,
                limit=max((limit or 120) * 3, 60),
            )

            for match in metadata_pattern.finditer(html_text):
                item_id = str(match.group(1) or "").upper()
                product_id = str(match.group(2) or "").upper()
                segment = html_text[match.start(): min(len(html_text), match.start() + 6000)]

                current_price_match = re.search(r'"current_price":\{"value":([0-9]+(?:\.[0-9]+)?)', segment, re.IGNORECASE)
                if not current_price_match:
                    continue

                url_path = _decode_embedded_text(match.group(3))
                url_fragments = _decode_embedded_text(match.group(4))
                category_id = str(match.group(5) or "").strip() or "ofertas"
                url_params = _decode_embedded_text(match.group(6))
                if not url_path:
                    continue
                if not url_path.startswith("http"):
                    url_path = f"https://{url_path.lstrip('/')}"
                affiliate_url = f"{url_path}{url_params}{url_fragments}"
                if affiliate_url in seen_urls:
                    continue
                seen_urls.add(affiliate_url)
                social_deep_url = _resolve_social_url_from_chrome_sessions(
                    affiliate_url,
                    item_id,
                    product_id,
                    client,
                    session_url_batches=session_url_batches,
                )
                selected_url = social_deep_url or affiliate_url

                title_match = re.search(r'"title":\{"text":"([^"]+)"', segment, re.IGNORECASE)
                previous_price_match = re.search(r'"previous_price":\{"value":([0-9]+(?:\.[0-9]+)?)', segment, re.IGNORECASE)
                shipping_text_match = re.search(r'"shipping":\{"text":"([^"]+)"', segment, re.IGNORECASE)
                shipping_extra_match = re.search(r'"additional_text":"([^"]*)"', segment, re.IGNORECASE)
                discount_label_match = re.search(r'"discount_label":\{"text":"([^"]+)"', segment, re.IGNORECASE)
                promotion_match = re.search(r'"promotions":\[\{"type":"[^"]+","text":"([^"]+)"', segment, re.IGNORECASE)
                picture_match = re.search(r'"pictures":\{"scale":"[^"]+","pictures":\[\{"id":"([^"]+)"', segment, re.IGNORECASE)
                image_url = ""
                if picture_match:
                    image_id = _decode_embedded_text(picture_match.group(1))
                    image_url = f"https://http2.mlstatic.com/D_NQ_NP_{image_id}-O.webp"

                offers.append(
                    {
                        "title": _decode_embedded_text((title_match.group(1) if title_match else "")).strip() or "Oferta Mercado Livre",
                        "description": "Oferta importada automaticamente da pagina social oficial do Mercado Livre.",
                        "price": float(current_price_match.group(1)),
                        "old_price": float(previous_price_match.group(1)) if previous_price_match else None,
                        "url": selected_url,
                        "image": image_url,
                        "category": category_id,
                        "tags": _tags_with_metadata(
                            ",".join(
                                part
                                for part in [
                                    "mercadolivre",
                                    "social_profile",
                                    social_deep_url or "",
                                ]
                                if part
                            )
                        ),
                        "featured": 1,
                        "sold_quantity": 0,
                        "coupon": None,
                        "item_id": item_id,
                        "product_id": product_id or _extract_meli_product_id(affiliate_url),
                        "affiliate_tag": os.getenv("MERCADOLIVRE_AFFILIATE_TAG", "").strip(),
                        "shipping": " | ".join(part for part in [
                            _decode_embedded_text(shipping_text_match.group(1)) if shipping_text_match else "",
                            _decode_embedded_text(shipping_extra_match.group(1)) if shipping_extra_match else "",
                        ] if part) or None,
                        "promotion_text": _decode_embedded_text((promotion_match.group(1) if promotion_match else "")).strip()
                        or _decode_embedded_text((discount_label_match.group(1) if discount_label_match else "")).strip()
                        or None,
                    }
                )
                if limit is not None and len(offers) >= limit:
                    break

            if limit is not None and len(offers) >= limit:
                break

            if limit is not None and len(offers) >= limit:
                break

            for affiliate_url in html_product_links:
                if affiliate_url in seen_urls:
                    continue
                seen_urls.add(affiliate_url)
                enriched_offer = _fetch_offer_details_from_affiliate_url(client, affiliate_url, access_token=access_token)
                if not enriched_offer:
                    continue
                offers.append(enriched_offer)
                if limit is not None and len(offers) >= limit:
                    break

        if limit is not None and len(offers) >= limit:
            break

    return offers


def _rank_offers(offers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    min_price = _safe_float(os.getenv("MELI_MIN_PRICE"), 0.0)
    max_price = _safe_float(os.getenv("MELI_MAX_PRICE"), 0.0)
    min_sold = _safe_int(os.getenv("MELI_MIN_SOLD", "0"), 0)
    max_results = _optional_positive_int_env("MELI_MAX_RESULTS", 120)
    sort_mode = os.getenv("MELI_SORT_MODE", "sales_low_price").strip().lower()

    filtered: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for offer in offers:
        url = (offer.get("url") or "").strip()
        price = _safe_float(offer.get("price"), 0.0)
        sold_quantity = _safe_int(offer.get("sold_quantity"), 0)
        dedupe_key = str(
            offer.get("product_id")
            or offer.get("item_id")
            or url
        ).strip()

        if not url or not dedupe_key or dedupe_key in seen_keys or price <= 0:
            continue
        if min_price and price < min_price:
            continue
        if max_price and price > max_price:
            continue
        if sold_quantity < min_sold:
            continue

        seen_keys.add(dedupe_key)
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
        if sort_mode == "sales_discount":
            return (-sold_quantity, -discount, price, -featured)
        return (-sold_quantity, price, -discount, -featured)

    filtered.sort(key=sort_key)
    if max_results is None:
        return filtered
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
                        "coupon": _extract_coupon_from_payload(item),
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
                        "coupon": _extract_coupon_from_payload(item),
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
                "coupon": _extract_coupon_from_payload(item),
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
        social_offers = _fetch_social_profile_offers(client, access_token=access_token)
        if social_offers:
            return _rank_offers(social_offers)

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
