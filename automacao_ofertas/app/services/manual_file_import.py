import csv
import io
import re
from typing import Any

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


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


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
    offer_link = row.get("Offer Link") or row.get("OfferLink") or row.get("offer_link") or ""
    product_link = row.get("Product Link") or row.get("ProductLink") or row.get("product_link") or ""
    candidate_link = offer_link or product_link
    if not candidate_link:
        return {}
    try:
        return preview_shopee_affiliate_links([candidate_link])[0]
    except Exception:  # noqa: BLE001
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

    items: list[dict[str, Any]] = []
    for row in rows:
        enriched = _enrich_shopee_row(row)
        title = _normalize_text(row.get("Item Name")) or _normalize_text(enriched.get("title")) or "Oferta Shopee"
        price = _normalize_price(row.get("Price"))
        shop_name = _normalize_text(row.get("Shop Name")) or "Shopee"
        sales_label = _parse_sales_label(row.get("Sales"))
        commission_rate = _normalize_text(row.get("Commission Rate"))
        commission_value = _normalize_text(row.get("Commission"))
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

        items.append(
            {
                "provider": "shopee",
                "store": "Shopee",
                "title": title,
                "description": _build_shopee_description(row),
                "price": price,
                "old_price": float(enriched["old_price"]) if enriched.get("old_price") else None,
                "url": offer_link or product_link,
                "canonical_url": product_link or final_url,
                "image": _normalize_text(enriched.get("image")),
                "category": category,
                "tags": tags,
                "featured": 0,
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
        item["selected"] = True
        if failed_links:
            item["file_warning"] = f"{len(failed_links)} link(s) do Mercado Livre foram ignorados por resposta invalida."

    return mercadolivre_items
