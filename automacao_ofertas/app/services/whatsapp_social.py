import os
from urllib.parse import quote
from typing import Any

import httpx

from app.services.offer_card_asset import generate_offer_square_card_asset
from app.services.social_meta import build_meta_post_previews, _store_label


def whatsapp_settings_snapshot() -> dict[str, Any]:
    api_base_url = (os.getenv("WHATSAPP_API_BASE_URL") or "").strip() or "https://waba-v2.360dialog.io"
    return {
        "api_base_url": api_base_url.rstrip("/"),
        "api_token_configured": bool((os.getenv("WHATSAPP_API_TOKEN") or "").strip()),
        "group_target": (os.getenv("WHATSAPP_GROUP_TARGET") or "").strip(),
    }


def _whatsapp_message_for_offer(item: dict[str, Any]) -> str:
    lines = [str(item["title"]).strip()]
    if item.get("coupon"):
        lines.append(f"Cupom: {item['coupon']}")
    lines.append(f"Preco: R$ {float(item['price'] or 0):.2f}".replace(".", ","))
    lines.append(f"Loja: {item['store']}")
    lines.append(f"Link: {item['cta_url']}")
    return "\n".join(lines)


def _whatsapp_web_share_url(message: str) -> str:
    return f"https://web.whatsapp.com/send?text={quote(message)}"


def generate_whatsapp_card_asset(offer: dict[str, Any]) -> dict[str, Any]:
    return generate_offer_square_card_asset(offer, suffix="wa")


def prepare_whatsapp_group_batch(db, limit: int = 5, offer_ids: list[int] | None = None) -> dict[str, Any]:
    previews = build_meta_post_previews(db, limit=limit, offer_ids=offer_ids, include_story_assets=False)
    settings = whatsapp_settings_snapshot()
    items = []

    for item in previews:
        offer_payload = {
            "id": item["offer_id"],
            "slug": item["slug"],
            "titulo": item["title"],
            "preco": item["price"],
            "preco_antigo": item.get("old_price"),
            "loja": item["store"],
            "categoria": item["category"],
            "imagem_url": item["image_url"],
            "url_afiliado": item.get("cta_url"),
            "cupom": item.get("coupon"),
        }
        card_asset = generate_whatsapp_card_asset(offer_payload)
        items.append(
            {
                "offer_id": item["offer_id"],
                "slug": item["slug"],
                "title": item["title"],
                "store": item["store"],
                "category": item["category"],
                "price": item.get("price"),
                "old_price": item.get("old_price"),
                "coupon": item.get("coupon"),
                "generated_filename": card_asset.get("filename"),
                "image_url": card_asset["public_url"] if card_asset.get("public_url") else item["image_url"],
                "product_image_url": item["image_url"],
                "cta_url": item["cta_url"],
                "site_url": item["offer_url"],
                "message": _whatsapp_message_for_offer(item),
                "web_share_url": _whatsapp_web_share_url(_whatsapp_message_for_offer(item)),
            }
        )

    if not items:
        if offer_ids:
            raise ValueError("Nenhuma oferta selecionada ficou elegivel para preparar o lote do WhatsApp.")
        raise ValueError("Nao ha ofertas elegiveis para preparar o lote do WhatsApp.")

    return {
        "ok": True,
        "platform": "whatsapp",
        "mode": "group",
        "count": len(items),
        "items": items,
        "delivery_status": "pending_connector",
        "group_target": settings["group_target"],
        "connector_ready": bool(settings["api_base_url"] and settings["api_token_configured"] and settings["group_target"]),
        "errors": [],
        "error_summary": "",
    }


def prepare_whatsapp_web_batch(db, limit: int = 5, offer_ids: list[int] | None = None) -> dict[str, Any]:
    batch = prepare_whatsapp_group_batch(db, limit=limit, offer_ids=offer_ids)
    return batch | {
        "mode": "web",
        "dispatch_status": "manual_web",
        "dispatch_reason": (
            "Modo local sem mensalidade: abre o WhatsApp Web com a mensagem pronta "
            "para voce escolher a conversa ou grupo e confirmar o envio manual."
        ),
    }


def _whatsapp_api_token() -> str:
    token = (os.getenv("WHATSAPP_API_TOKEN") or "").strip()
    if not token:
        raise ValueError("WHATSAPP_API_TOKEN nao configurado.")
    return token


def _whatsapp_group_target() -> str:
    target = (os.getenv("WHATSAPP_GROUP_TARGET") or "").strip()
    if not target:
        raise ValueError("WHATSAPP_GROUP_TARGET nao configurado.")
    return target


def _whatsapp_headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "D360-API-KEY": _whatsapp_api_token(),
    }


def list_whatsapp_groups(limit: int = 100) -> dict[str, Any]:
    settings = whatsapp_settings_snapshot()
    if not settings["api_token_configured"]:
        raise ValueError("WHATSAPP_API_TOKEN nao configurado.")

    params = {"limit": max(1, min(int(limit), 1024))}
    with httpx.Client(base_url=settings["api_base_url"], timeout=30) as client:
        response = client.get("/groups", params=params, headers=_whatsapp_headers())
        response.raise_for_status()
        data = response.json()

    raw_items = []
    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            raw_items = data["data"]
        elif isinstance(data.get("groups"), list):
            raw_items = data["groups"]
        elif isinstance(data.get("items"), list):
            raw_items = data["items"]
    elif isinstance(data, list):
        raw_items = data

    items = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        group_id = str(item.get("id") or item.get("group_id") or "").strip()
        subject = str(item.get("subject") or item.get("name") or group_id).strip() or group_id
        if not group_id:
            continue
        items.append(
            {
                "group_id": group_id,
                "subject": subject,
                "description": str(item.get("description") or "").strip(),
                "raw": item,
            }
        )

    return {"ok": True, "count": len(items), "items": items, "raw": data}


def _send_whatsapp_group_item(client: httpx.Client, item: dict[str, Any]) -> dict[str, Any]:
    group_target = _whatsapp_group_target()
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "group",
        "to": group_target,
    }

    message_text = _whatsapp_message_for_offer(item)
    image_url = (item.get("image_url") or "").strip()
    if image_url:
        payload["type"] = "image"
        payload["image"] = {
            "link": image_url,
            "caption": message_text[:1024],
        }
    else:
        payload["type"] = "text"
        payload["text"] = {
            "preview_url": True,
            "body": message_text,
        }

    response = client.post("/messages", json=payload, headers=_whatsapp_headers())
    response.raise_for_status()
    return response.json()


def send_whatsapp_group_batch(db, limit: int = 5, offer_ids: list[int] | None = None) -> dict[str, Any]:
    batch = prepare_whatsapp_group_batch(db, limit=limit, offer_ids=offer_ids)
    settings = whatsapp_settings_snapshot()
    if not batch["items"]:
        raise ValueError("Nao ha ofertas elegiveis para preparar o lote do WhatsApp.")

    if not (settings["api_base_url"] and settings["api_token_configured"] and settings["group_target"]):
        return batch | {
            "dispatch_status": "prepared_only",
            "dispatch_reason": (
                "Connector do WhatsApp ainda nao configurado por completo. "
                "Preencha API base, token e grupo alvo para habilitar o envio real."
            ),
            "connector_ready": False,
        }

    sent_items = []
    errors = []
    with httpx.Client(base_url=settings["api_base_url"], timeout=30) as client:
        for item in batch["items"]:
            try:
                result = _send_whatsapp_group_item(client, item)
                sent_items.append(item | {"result": result})
            except Exception as exc:  # noqa: BLE001
                errors.append(
                    {
                        "offer_id": item["offer_id"],
                        "title": item["title"],
                        "platform": "whatsapp",
                        "error": str(exc),
                    }
                )

    return batch | {
        "ok": len(sent_items) > 0,
        "count": len(sent_items),
        "items": sent_items,
        "errors": errors,
        "error_summary": (errors[0]["error"] if errors else ""),
        "dispatch_status": "sent" if sent_items and not errors else "partial" if sent_items else "error",
        "dispatch_reason": "",
        "connector_ready": True,
    }
