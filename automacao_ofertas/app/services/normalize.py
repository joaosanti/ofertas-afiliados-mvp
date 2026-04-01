import json
import os
import re
from base64 import urlsafe_b64encode
from urllib.parse import parse_qs, parse_qsl, quote_plus, unquote, urlencode, urlparse, urlunparse

from app.schemas import NormalizedOffer


def repair_text(value: str | None) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    suspicious = ("Ã", "Â", "â€™", "â€œ", "â€", "�")
    if any(token in text for token in suspicious):
        try:
            repaired = text.encode("latin-1").decode("utf-8")
            if repaired:
                text = repaired
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass

    return text


def build_slug(title: str) -> str:
    slug = "".join(c.lower() if c.isalnum() else "-" for c in title)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:170] or "item"


def _unwrap_redirect_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower()
    if host not in {"l.facebook.com", "lm.facebook.com"}:
        return raw

    target = (parse_qs(parsed.query, keep_blank_values=True).get("u") or [raw])[0]
    return unquote(target).strip() or raw


def _normalize_meli_item_id(value: str | None) -> str | None:
    raw = repair_text(value).upper().strip().replace("-", "")
    if not raw:
        return None

    match = re.search(r"(MLB)(\d+)", raw)
    if match:
        return f"{match.group(1)}{match.group(2)}"

    if raw.isdigit():
        return f"MLB{raw}"

    return None


def _extract_meli_item_id(url: str) -> str | None:
    parsed = urlparse(url)

    for values in (
        parse_qs(parsed.query, keep_blank_values=True),
        parse_qs(parsed.fragment, keep_blank_values=True),
    ):
        for key in ("wid", "item_id", "item"):
            candidate = _normalize_meli_item_id((values.get(key) or [None])[0])
            if candidate:
                return candidate
        for entry in values.get("pdp_filters") or []:
            match = re.search(r"item_id:((?:MLB)?\d+)", unquote(entry), re.IGNORECASE)
            if match:
                candidate = _normalize_meli_item_id(match.group(1))
                if candidate:
                    return candidate

    path_match = re.search(r"(MLB)[-_]?(\d+)", parsed.path, re.IGNORECASE)
    if path_match:
        return f"{path_match.group(1).upper()}{path_match.group(2)}"

    return None


def _is_meli_social_link(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "mercadolivre" not in host and "mercadolibre" not in host:
        return False
    path = (parsed.path or "").lower()
    query = parse_qs(parsed.query, keep_blank_values=True)
    return "/social/" in path or "matt_tool" in query


def _is_meli_profile_or_list_social_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    path = (parsed.path or "").lower()
    if "mercadolivre" not in host and "mercadolibre" not in host:
        return False
    if "/social/" not in path:
        return False
    if "/lists/" in path:
        return True
    query = parse_qs(parsed.query, keep_blank_values=True)
    return not bool((query.get("ref") or [None])[0])


def _has_meli_affiliate_marker(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    if "mercadolivre" not in host and "mercadolibre" not in host:
        return False

    query = parse_qs(parsed.query, keep_blank_values=True)
    fragment = parse_qs(parsed.fragment, keep_blank_values=True)
    combined = {**query, **fragment}

    wid = (combined.get("wid") or [None])[0]
    sid = (combined.get("sid") or [None])[0]
    polycard = (combined.get("polycard_client") or [None])[0]
    source = (combined.get("source") or [None])[0]
    reco_client = (combined.get("reco_client") or [None])[0]
    return bool(
        _is_meli_social_link(url)
        or ("matt_tool" in query)
        or wid
        or (wid and sid == "affiliates")
        or (wid and polycard == "affiliates")
        or (wid and sid == "recos" and source == "affiliate-profile")
        or (wid and source == "affiliate-profile")
        or (wid and reco_client == "home_affiliate-profile")
        or (wid and isinstance(polycard, str) and "affiliate-profile" in polycard)
    )


def _extract_amazon_asin(url: str, product_id: str | None = None) -> str | None:
    candidate = repair_text(product_id).upper()
    if re.fullmatch(r"[A-Z0-9]{10}", candidate):
        return candidate

    match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", (url or "").strip(), re.IGNORECASE)
    if match:
        return match.group(1).upper()

    return None


def ensure_affiliate_link(url: str, store: str, tag: str | None = None, item_id: str | None = None, product_id: str | None = None) -> str:
    url = _unwrap_redirect_url(url)
    if not tag:
        return url

    normalized_store = store.strip().lower()

    if normalized_store == "mercado livre":
        if _has_meli_affiliate_marker(url):
            return url

        template = os.getenv("MERCADOLIVRE_AFFILIATE_URL_TEMPLATE", "").strip()
        if template:
            return (
                template
                .replace("{url}", url)
                .replace("{encoded_url}", quote_plus(url))
                .replace("{tag}", tag)
                .replace("{item_id}", item_id or "")
                .replace("{product_id}", product_id or "")
            )

        # Do not fabricate Mercado Livre affiliate parameters locally.
        # Tracking must come from an official affiliate link or an explicit template.
        return url

    if normalized_store == "shopee":
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower()
        query = parse_qs(parsed.query, keep_blank_values=True)
        if "shopee" in host and (
            host.startswith("s.shopee.")
            or (query.get("utm_medium") or [""])[0] == "affiliates"
            or bool((query.get("mmp_pid") or [None])[0])
            or bool((query.get("utm_source") or [None])[0])
        ):
            return url
        return url

    if normalized_store == "amazon":
        parsed = urlparse(url)
        asin = _extract_amazon_asin(url, product_id)
        if asin:
            host = parsed.netloc or "www.amazon.com.br"
            return urlunparse((parsed.scheme or "https", host, f"/dp/{asin}", "", urlencode([("tag", tag)]), ""))

        query_items = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() != "tag"]
        query_items.append(("tag", tag))
        return urlunparse(parsed._replace(query=urlencode(query_items), fragment=""))

    sep = "&" if "?" in url else "?"
    return f"{url}{sep}aff={tag}"


def ensure_tags(tags: str | None, store: str, affiliate_tag: str | None) -> str | None:
    base_tags = [repair_text(tag) for tag in (tags or "").split(",") if repair_text(tag)]
    normalized_store = store.strip().lower()

    if normalized_store == "mercado livre" and affiliate_tag:
        marker = f"meli_grant:{affiliate_tag}"
        if marker not in base_tags:
            base_tags.append(marker)

    if normalized_store == "mercado livre":
        base_tags = [candidate for candidate in base_tags if not _is_meli_social_link(candidate)]
        for candidate in base_tags:
            if candidate.startswith("meli_social_url:"):
                return ",".join(base_tags) or None

        social_url = next(
            (
                repair_text(candidate)
                for candidate in (tags or "").split(",")
                if _is_meli_social_link(repair_text(candidate)) and not _is_meli_profile_or_list_social_url(repair_text(candidate))
            ),
            "",
        )
        if social_url:
            encoded_social = urlsafe_b64encode(social_url.encode("utf-8")).decode("ascii").rstrip("=")
            base_tags.append(f"meli_social_url:{encoded_social}")

    return ",".join(base_tags) or None


def _tag_url(tags: str | None, prefix: str, url: str | None) -> str | None:
    normalized_url = repair_text(url)
    if not normalized_url.startswith(("http://", "https://")):
        return tags

    base_tags = [repair_text(tag) for tag in (tags or "").split(",") if repair_text(tag)]
    base_tags = [candidate for candidate in base_tags if not candidate.startswith(prefix)]
    encoded_url = urlsafe_b64encode(normalized_url.encode("utf-8")).decode("ascii").rstrip("=")
    base_tags.append(f"{prefix}{encoded_url}")
    return ",".join(dict.fromkeys(base_tags)) or None


def _normalize_url_list(value: object) -> list[str]:
    candidates: list[str] = []
    if isinstance(value, str):
        raw = repair_text(value)
        if not raw:
            return []
        if raw.startswith("[") and raw.endswith("]"):
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                decoded = None
            if isinstance(decoded, list):
                value = decoded
            else:
                value = [raw]
        else:
            value = [raw]

    if isinstance(value, (list, tuple, set)):
        candidates.extend(repair_text(str(item)) for item in value)

    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate.startswith(("http://", "https://")):
            continue
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


def normalize_offer(raw: dict, store: str, affiliate_tag: str | None = None) -> NormalizedOffer:
    clean_store = repair_text(store)
    clean_url = repair_text(raw.get("url", "#"))
    social_url = repair_text(raw.get("social_url"))
    raw_tags = repair_text(raw.get("tags"))
    raw_image_url = repair_text(raw.get("image"))
    raw_video_url = repair_text(raw.get("video_url"))
    image_urls = _normalize_url_list(raw.get("image_urls"))
    video_urls = _normalize_url_list(raw.get("video_urls"))
    requires_manual_review = bool(raw.get("price_missing_review"))
    primary_url = clean_url

    if raw_image_url and raw_image_url not in image_urls:
        image_urls.insert(0, raw_image_url)
    elif not raw_image_url and image_urls:
        raw_image_url = image_urls[0]

    if raw_video_url and raw_video_url not in video_urls:
        video_urls.insert(0, raw_video_url)
    elif not raw_video_url and video_urls:
        raw_video_url = video_urls[0]

    if clean_store.strip().lower() == "mercado livre":
        if social_url and not _is_meli_profile_or_list_social_url(social_url):
            raw_tags = ",".join(part for part in [raw_tags, social_url] if part)

    if raw_video_url:
        site_base_url = (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/").lower()
        if raw_video_url.lower().startswith(f"{site_base_url}/uploads/ofertas_videos/"):
            raw_tags = _tag_url(raw_tags, "offer_video_url:", raw_video_url) or ""
        elif clean_store.strip().lower() == "shopee":
            raw_tags = _tag_url(raw_tags, "shopee_video_url:", raw_video_url) or ""
        else:
            raw_tags = _tag_url(raw_tags, "offer_video_url:", raw_video_url) or ""

    if requires_manual_review:
        raw_tags = ",".join(part for part in [raw_tags, "manual_review", "price_missing"] if part)

    return NormalizedOffer(
        titulo=repair_text(raw.get("title", "Oferta sem titulo")),
        descricao=repair_text(raw.get("description", "")),
        preco=float(raw.get("price", 0)),
        preco_antigo=float(raw["old_price"]) if raw.get("old_price") not in (None, "") else None,
        desconto_percentual=int(float(raw["discount_percent"])) if raw.get("discount_percent") not in (None, "") else None,
        preco_pix=float(raw["pix_price"]) if raw.get("pix_price") not in (None, "") else None,
        preco_outros_meios=float(raw["other_price"]) if raw.get("other_price") not in (None, "") else None,
        parcelas_texto=repair_text(raw.get("installments")) or None,
        frete_texto=repair_text(raw.get("shipping")) or None,
        avaliacao_nota=float(raw["rating"]) if raw.get("rating") not in (None, "") else None,
        avaliacao_total=int(float(raw["rating_count"])) if raw.get("rating_count") not in (None, "") else None,
        promocao_texto=repair_text(raw.get("promotion_text")) or None,
        loja=clean_store,
        url_afiliado=ensure_affiliate_link(
            primary_url,
            clean_store,
            affiliate_tag,
            raw.get("item_id"),
            raw.get("product_id"),
        ),
        cupom=repair_text(raw.get("coupon")) or None,
        imagem_url=raw_image_url or None,
        imagem_urls=image_urls or None,
        video_urls=video_urls or None,
        categoria=repair_text(raw.get("category", "ofertas")),
        tags=ensure_tags(raw_tags, clean_store, affiliate_tag),
        destaque=int(raw.get("featured", 0)),
        ativo=0 if requires_manual_review else 1,
    )
