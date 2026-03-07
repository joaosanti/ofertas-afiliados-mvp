import os
from typing import Any

import httpx


def fetch_tiktok_offers() -> list[dict[str, Any]]:
    # Para produção: integrar TikTok Shop Open API autenticada.
    # Neste MVP: aceita feed JSON do seu pipeline (n8n/Make/script oficial).
    feed_url = os.getenv("TIKTOK_FEED_URL", "").strip()
    affiliate_tag = os.getenv("TIKTOK_AFFILIATE_TAG", "")

    if not feed_url:
        return []

    with httpx.Client(timeout=20) as client:
        resp = client.get(feed_url)
        resp.raise_for_status()
        data = resp.json()

    offers: list[dict[str, Any]] = []
    for item in data if isinstance(data, list) else data.get("items", []):
        offers.append(
            {
                "title": item.get("title", "Oferta TikTok"),
                "description": item.get("description", ""),
                "price": float(item.get("price") or 0),
                "old_price": float(item.get("old_price")) if item.get("old_price") else None,
                "url": item.get("url", "#"),
                "image": item.get("image", ""),
                "category": item.get("category", "ofertas"),
                "tags": item.get("tags", "tiktok"),
                "featured": int(item.get("featured", 0)),
                "affiliate_tag": affiliate_tag,
            }
        )

    return offers
