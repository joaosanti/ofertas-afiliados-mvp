import csv
import io
import mimetypes
import os
import re
import secrets
import unicodedata
from base64 import urlsafe_b64encode
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from app.collectors.shopee import preview_shopee_affiliate_links
from app.services.category_inference import infer_category_label
from app.services.manual_link_import import preview_manual_affiliate_links


def _safe_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    raw = str(value).strip()
    if not raw:
        return None
    raw = raw.replace("R$", "").replace(" ", "").strip()
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _normalize_price(value: Any) -> float:
    return round(_safe_float(value) or 0.0, 2)


def _discount_percent(price: float, old_price: Any) -> int | None:
    previous = _safe_float(old_price) or 0.0
    current = float(price or 0.0)
    if current <= 0 or previous <= current:
        return None
    return int(round(((previous - current) / previous) * 100))


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_lookup_key(value: Any) -> str:
    text = _normalize_text(value)
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = normalized.replace("?", "i")
    normalized = re.sub(r"[^a-z0-9]+", "", normalized.lower())
    return normalized


def _site_base_url() -> str:
    return (os.getenv("SITE_BASE_URL") or "https://zeropreco.com.br").rstrip("/")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _offer_video_upload_dir() -> Path:
    directory = _project_root() / "public_html" / "uploads" / "ofertas_videos"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _offer_video_public_url(filename: str) -> str:
    return f"{_site_base_url()}/uploads/ofertas_videos/{filename}"


def _video_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
        "Accept": "*/*",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": _site_base_url(),
    }


def _row_value(row: dict[str, str], *keys: str) -> str:
    lowered = {_normalize_lookup_key(key): _normalize_text(value) for key, value in (row or {}).items()}
    for key in keys:
        value = lowered.get(_normalize_lookup_key(key), "")
        if value:
            return value
    return ""


def _shopee_csv_import_limit() -> int:
    raw = _normalize_text(os.getenv("SHOPEE_CSV_IMPORT_LIMIT") or "100")
    try:
        parsed = int(raw)
    except ValueError:
        return 100
    return max(1, min(parsed, 100))


def _extract_csv_video_url(row: dict[str, str]) -> str:
    return _row_value(
        row,
        "Video URL",
        "VideoURL",
        "Video Url",
        "Vídeo URL",
        "Vídeo Url",
        "video_url",
        "video url",
        "Video",
        "video",
        "Video Link",
        "Link do video",
        "Link do vídeo",
        "video_link",
        "video link",
        "Video MP4",
        "video_mp4",
    )


def _upsert_tag_url(tags: str, prefix: str, url: str) -> str:
    normalized_url = _normalize_text(url)
    if not normalized_url.startswith(("http://", "https://")):
        return tags

    parts = [part.strip() for part in str(tags or "").split(",") if part.strip()]
    parts = [part for part in parts if not part.startswith(prefix)]
    encoded_url = urlsafe_b64encode(normalized_url.encode("utf-8")).decode("ascii").rstrip("=")
    parts.append(f"{prefix}{encoded_url}")
    return ",".join(dict.fromkeys(parts))


def _guess_video_extension(video_url: str, content_type: str) -> str:
    parsed = urlparse(video_url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in {".mp4", ".webm", ".mov", ".m4v"}:
        return suffix

    normalized_type = str(content_type or "").split(";")[0].strip().lower()
    mapped = mimetypes.guess_extension(normalized_type) or ""
    if mapped == ".mpg":
        mapped = ".mp4"
    if mapped in {".mp4", ".webm", ".mov", ".m4v"}:
        return mapped
    return ".mp4"


def _download_offer_video(video_url: str) -> str:
    normalized_url = _normalize_text(video_url)
    if not normalized_url.startswith(("http://", "https://")):
        return ""

    upload_limit = 80 * 1024 * 1024
    try:
        with httpx.Client(timeout=45, follow_redirects=True, headers=_video_headers()) as client:
            with client.stream("GET", normalized_url) as response:
                response.raise_for_status()
                content_type = (response.headers.get("content-type") or "").lower()
                if content_type and not content_type.startswith("video/"):
                    return ""

                declared_length = int(response.headers.get("content-length") or 0)
                if declared_length > upload_limit:
                    return ""

                extension = _guess_video_extension(normalized_url, content_type)
                filename = f"oferta-video-auto-{secrets.token_hex(8)}{extension}"
                target_path = _offer_video_upload_dir() / filename
                written = 0
                with target_path.open("wb") as output_file:
                    for chunk in response.iter_bytes():
                        if not chunk:
                            continue
                        written += len(chunk)
                        if written > upload_limit:
                            output_file.close()
                            target_path.unlink(missing_ok=True)
                            return ""
                        output_file.write(chunk)

                if written <= 0:
                    target_path.unlink(missing_ok=True)
                    return ""

                return _offer_video_public_url(filename)
    except Exception:  # noqa: BLE001
        return ""


def _parse_sales_label(value: Any) -> str:
    raw = _normalize_text(value)
    return raw or "0"


def _decode_csv_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _detect_csv_dialect(sample: str) -> csv.Dialect:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;")
    except csv.Error:
        return csv.excel


def _parse_csv_rows(content: bytes) -> list[dict[str, str]]:
    text = _decode_csv_bytes(content)
    dialect = _detect_csv_dialect(text[:2048])
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for row in reader:
        normalized = {str(key or "").strip(): _normalize_text(value) for key, value in (row or {}).items()}
        if any(normalized.values()):
            rows.append(normalized)
    return rows


def _build_shopee_description(row: dict[str, str]) -> str:
    parts = []
    if row.get("Shop Name"):
        parts.append(f"Loja: {row['Shop Name']}")
    if row.get("Sales"):
        parts.append(f"Vendas: {row['Sales']}")
    if row.get("Commission Rate"):
        parts.append(f"Comissao: {row['Commission Rate']}")
    if row.get("Commission"):
        parts.append(f"Retorno estimado: {row['Commission']}")
    return " | ".join(parts) or "Oferta Shopee importada por arquivo."


def _enrich_shopee_row(row: dict[str, str]) -> dict[str, Any]:
    offer_link = _row_value(row, "Offer Link", "OfferLink", "offer_link")
    product_link = _row_value(row, "Product Link", "ProductLink", "product_link")
    candidate_link = offer_link or product_link
    if not candidate_link:
        return {}
    try:
        return preview_shopee_affiliate_links([candidate_link])[0]
    except Exception:  # noqa: BLE001
        pass
    return {}


def preview_shopee_csv_file(content: bytes, filename: str = "") -> list[dict[str, Any]]:
    if not content:
        raise ValueError("Envie um arquivo CSV com produtos da Shopee.")

    rows = _parse_csv_rows(content)
    if not rows:
        raise ValueError("O arquivo enviado nao trouxe nenhuma linha de produto.")

    required = {"Item Id", "Item Name", "Price", "Product Link", "Offer Link"}
    available = set(rows[0].keys())
    missing = [field for field in required if field not in available]
    if missing:
        raise ValueError(f"CSV da Shopee invalido. Campos ausentes: {', '.join(missing)}")

    original_count = len(rows)
    limit = _shopee_csv_import_limit()
    rows = rows[:limit]
    truncated = original_count > len(rows)

    items: list[dict[str, Any]] = []
    for row in rows:
        enriched = _enrich_shopee_row(row)
        title = _normalize_text(row.get("Item Name")) or _normalize_text(enriched.get("title")) or "Oferta Shopee"
        price = _normalize_price(row.get("Price"))
        shop_name = _normalize_text(row.get("Shop Name")) or "Shopee"
        sales_label = _parse_sales_label(row.get("Sales"))
        commission_rate = _normalize_text(row.get("Commission Rate"))
        commission_value = _normalize_text(row.get("Commission"))
        coupon = _normalize_text(row.get("Coupon")) or _normalize_text(row.get("coupon")) or _normalize_text(row.get("Voucher")) or _normalize_text(row.get("voucher"))
        offer_link = _normalize_text(row.get("Offer Link"))
        product_link = _normalize_text(row.get("Product Link"))
        category = infer_category_label(
            title,
            shop_name,
            product_link,
            offer_link,
            enriched.get("description"),
        )
        final_url = _normalize_text(enriched.get("canonical_url")) or product_link or offer_link
        affiliate_code = ""
        if "an_" in final_url or "an_" in offer_link:
            source = final_url if "an_" in final_url else offer_link
            start = source.find("an_")
            end = start
            while end < len(source) and (source[end].isalnum() or source[end] in {"_", "-"}):
                end += 1
            affiliate_code = source[start:end]

        tags = ",".join(
            filter(
                None,
                [
                    "shopee",
                    "arquivo",
                    f"shop:{shop_name.lower().replace(' ', '-')}" if shop_name else "",
                    f"sales:{sales_label}" if sales_label else "",
                    f"commission-rate:{commission_rate}" if commission_rate else "",
                ],
            )
        )
        csv_video_url = _extract_csv_video_url(row)
        imported_video_url = _normalize_text(enriched.get("video_url")) or csv_video_url
        uploaded_video_url = _download_offer_video(imported_video_url) if imported_video_url else ""
        for candidate in str(enriched.get("tags") or "").split(","):
            cleaned_candidate = candidate.strip()
            if cleaned_candidate.startswith("shopee_video_url:") and cleaned_candidate not in tags:
                tags = ",".join(filter(None, [tags, cleaned_candidate]))
        if imported_video_url and "shopee_video_url:" not in tags:
            tags = _upsert_tag_url(tags, "shopee_video_url:", imported_video_url)
        if uploaded_video_url:
            tags = _upsert_tag_url(tags, "offer_video_url:", uploaded_video_url)

        enriched_old_price = float(enriched["old_price"]) if enriched.get("old_price") else None
        items.append(
            {
                "provider": "shopee",
                "store": "Shopee",
                "title": title,
                "description": _build_shopee_description(row),
                "price": price,
                "old_price": enriched_old_price,
                "discount_percent": enriched.get("discount_percent") or _discount_percent(price, enriched_old_price),
                "pix_price": enriched.get("pix_price"),
                "other_price": enriched.get("other_price"),
                "installments": _normalize_text(enriched.get("installments")) or None,
                "shipping": _normalize_text(enriched.get("shipping")) or None,
                "rating": enriched.get("rating"),
                "rating_count": enriched.get("rating_count"),
                "promotion_text": _normalize_text(enriched.get("promotion_text")) or None,
                "url": offer_link or product_link,
                "canonical_url": product_link or final_url,
                "image": _normalize_text(enriched.get("image")),
                "image_urls": enriched.get("image_urls") or ([_normalize_text(enriched.get("image"))] if _normalize_text(enriched.get("image")) else []),
                "category": category,
                "tags": tags,
                "featured": 0,
                "coupon": coupon or None,
                "video_url": uploaded_video_url or imported_video_url,
                "video_urls": enriched.get("video_urls") or ([imported_video_url] if imported_video_url else []),
                "affiliate_detected": bool(offer_link),
                "affiliate_code": affiliate_code or None,
                "selected": True,
                "item_id": _normalize_text(row.get("Item Id")),
                "sales_label": sales_label,
                "commission_rate": commission_rate,
                "commission_value": commission_value,
                "source_file": filename,
            }
        )

    if truncated:
        warning = f"Arquivo limitado a {limit} linhas para evitar demora no import da Shopee."
        for item in items:
            item["file_warning"] = warning

    return items


def _parse_text_links(content: bytes) -> list[str]:
    if not content:
        return []
    text = _decode_csv_bytes(content)
    links = re.findall(r"https?://[^\s]+", text, flags=re.IGNORECASE)
    deduped: list[str] = []
    seen: set[str] = set()
    for link in links:
        normalized = link.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def preview_amazon_txt_file(content: bytes, filename: str = "") -> list[dict[str, Any]]:
    if not content:
        raise ValueError("Envie um arquivo TXT com links da Amazon.")

    links = _parse_text_links(content)
    if not links:
        raise ValueError("O TXT nao trouxe links validos da Amazon.")

    amazon_items: list[dict[str, Any]] = []
    failed_links: list[str] = []
    for link in links:
        try:
            items = preview_manual_affiliate_links([link])
        except Exception:  # noqa: BLE001
            failed_links.append(link)
            continue
        amazon_items.extend(item for item in items if str(item.get("provider") or "").lower() == "amazon")

    if not amazon_items:
        if failed_links:
            raise ValueError("Nenhum link da Amazon valido foi identificado no TXT enviado. Alguns links retornaram em formato bloqueado pela Amazon.")
        raise ValueError("Nenhum link da Amazon valido foi identificado no TXT enviado.")

    for item in amazon_items:
        item["source_file"] = filename
        item["selected"] = True
        if failed_links:
            item["file_warning"] = f"{len(failed_links)} link(s) da Amazon foram ignorados por resposta invalida."

    return amazon_items


def preview_mercadolivre_txt_file(content: bytes, filename: str = "") -> list[dict[str, Any]]:
    if not content:
        raise ValueError("Envie um arquivo TXT com links do Mercado Livre.")

    links = _parse_text_links(content)
    if not links:
        raise ValueError("O TXT nao trouxe links validos do Mercado Livre.")

    mercadolivre_items: list[dict[str, Any]] = []
    failed_links: list[str] = []
    for link in links:
        try:
            items = preview_manual_affiliate_links([link])
        except Exception:  # noqa: BLE001
            failed_links.append(link)
            continue
        mercadolivre_items.extend(item for item in items if str(item.get("provider") or "").lower() == "mercadolivre")

    if not mercadolivre_items:
        if failed_links:
            raise ValueError("Nenhum link do Mercado Livre valido foi identificado no TXT enviado. Alguns links retornaram em formato invalido.")
        raise ValueError("Nenhum link do Mercado Livre valido foi identificado no TXT enviado.")

    for item in mercadolivre_items:
        item["source_file"] = filename
        item["selected"] = bool(item.get("import_allowed", item.get("affiliate_detected")))
        warnings: list[str] = []
        if failed_links:
            warnings.append(f"{len(failed_links)} link(s) do Mercado Livre foram ignorados por resposta invalida.")
        if not item.get("affiliate_detected"):
            base_warning = item.get("affiliate_warning") or "Link sem marcador oficial de afiliado."
            warnings.append(f"{base_warning} Revise este item antes de importar.")
        if warnings:
            item["file_warning"] = " ".join(warnings)

    return mercadolivre_items
