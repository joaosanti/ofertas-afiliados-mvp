from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import re
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.sftp_deploy import ensure_stories_dir, story_public_url


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ZERO_PRECO_LOGO = PROJECT_ROOT / "public_html" / "assets" / "img" / "logo-zp.png"
ZERO_PRECO_LOGO_URL = "https://zeropreco.com.br/assets/img/logo-zp.png"


def _browser_headers() -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/132.0.0.0 Safari/537.36"
        ),
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", (value or "").strip()).strip("-").lower()
    cleaned = cleaned[:80].rstrip("-")
    return cleaned or "oferta"


def _money(value: Any) -> str:
    return f"R$ {float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _discount_percent(offer: dict[str, Any]) -> int:
    explicit = offer.get("desconto_percentual")
    if explicit not in (None, ""):
        try:
            return max(0, int(float(explicit)))
        except (TypeError, ValueError):
            pass
    try:
        price = float(offer.get("preco") or 0)
        old_price = float(offer.get("preco_antigo") or 0)
    except (TypeError, ValueError):
        return 0
    if old_price <= price or old_price <= 0 or price <= 0:
        return 0
    return max(0, int(round((old_price - price) / old_price * 100)))


def _format_rating(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return f"{float(value):.1f}".replace(".", ",")
    except (TypeError, ValueError):
        return None


def _format_rating_count(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        return f"{int(float(value)):,}".replace(",", ".")
    except (TypeError, ValueError):
        return None


def _offer_layout_data(offer: dict[str, Any]) -> dict[str, Any]:
    old_price = offer.get("preco_antigo")
    has_old_price = old_price not in (None, "", 0, 0.0)
    discount = _discount_percent(offer)
    pix_price = offer.get("preco_pix")
    has_pix_price = pix_price not in (None, "", 0, 0.0)
    installments = _clean_text(offer.get("parcelas_texto"))
    shipping = _clean_text(offer.get("frete_texto"))
    promo = _clean_text(offer.get("promocao_texto"))
    rating = _format_rating(offer.get("avaliacao_nota"))
    rating_count = _format_rating_count(offer.get("avaliacao_total"))

    if has_old_price and discount > 0:
        variant = "deal"
    elif has_pix_price and installments:
        variant = "payment"
    elif shipping or rating:
        variant = "trust"
    else:
        variant = "clean"

    badges: list[str] = []
    if shipping:
        badges.append(shipping)
    if rating and rating_count:
        badges.append(f"{rating} estrelas ({rating_count})")
    elif rating:
        badges.append(f"{rating} estrelas")
    if promo:
        badges.append(promo[:58].rstrip(" -|,.;") + ("..." if len(promo) > 58 else ""))
    badges = badges[:2]

    return {
        "variant": variant,
        "discount": discount,
        "has_old_price": has_old_price,
        "old_price_text": _money(old_price) if has_old_price else "",
        "current_price_text": _money(offer["preco"]),
        "pix_price_text": _money(pix_price) if has_pix_price else "",
        "installments": installments,
        "shipping": shipping,
        "rating": rating,
        "rating_count": rating_count,
        "promo": promo,
        "badges": badges,
    }


def _fit_font_for_width(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, min_size: int = 26, bold: bool = True):
    size = start_size
    font = _load_font(size, bold=bold)
    while size > min_size:
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
          return font
        size -= 2
        font = _load_font(size, bold=bold)
    return font


def _load_font(size: int, bold: bool = False):
    candidates = []
    if bold:
        candidates.extend(
            [
                r"C:\Windows\Fonts\arialbd.ttf",
                r"C:\Windows\Fonts\segoeuib.ttf",
                r"C:\Windows\Fonts\calibrib.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        ]
    )
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _contain_remote_product_image(url: str, size: tuple[int, int]) -> Image.Image | None:
    image_url = (url or "").strip()
    if not image_url:
        return None
    try:
        with httpx.Client(timeout=25, follow_redirects=True, headers=_browser_headers()) as client:
            response = client.get(image_url)
            response.raise_for_status()
        if not response.content:
            return None
        with Image.open(BytesIO(response.content)) as source:
            converted = source.convert("RGB")
            contained = ImageOps.contain(converted, size, method=Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", size, "#ffffff")
            offset_x = (size[0] - contained.width) // 2
            offset_y = (size[1] - contained.height) // 2
            canvas.paste(contained, (offset_x, offset_y))
            return canvas
    except Exception:  # noqa: BLE001
        return None


def _load_zero_preco_logo(size: tuple[int, int]) -> Image.Image | None:
    try:
        if ZERO_PRECO_LOGO.exists():
            with Image.open(ZERO_PRECO_LOGO) as source:
                logo = source.convert("RGBA")
                logo.thumbnail(size, Image.Resampling.LANCZOS)
                return logo
    except Exception:  # noqa: BLE001
        pass

    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            response = client.get(ZERO_PRECO_LOGO_URL)
            response.raise_for_status()
        with Image.open(BytesIO(response.content)) as source:
            logo = source.convert("RGBA")
            logo.thumbnail(size, Image.Resampling.LANCZOS)
            return logo
    except Exception:  # noqa: BLE001
        return None


def generate_offer_square_card_asset(offer: dict[str, Any], *, suffix: str = "card") -> dict[str, Any]:
    filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}-{suffix}.jpg"
    destination = ensure_stories_dir() / filename

    image = Image.new("RGB", (1080, 1080), "#efe9df")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1080, 1080), fill="#efe9df")

    draw.rounded_rectangle((42, 36, 1038, 1040), radius=40, fill="#ffffff")
    draw.rounded_rectangle((42, 36, 1038, 162), radius=40, fill="#4d1d95")
    draw.rectangle((42, 118, 1038, 162), fill="#4d1d95")
    site_badge_box = (662, 52, 980, 146)
    draw.rounded_rectangle(site_badge_box, radius=46, fill="#ffcb19")

    brand_font = _load_font(42, bold=True)
    title_font = _load_font(36, bold=True)
    meta_font = _load_font(22, bold=True)
    price_label_font = _load_font(18, bold=True)
    site_font = _load_font(28, bold=True)

    logo_drawn = False
    logo = _load_zero_preco_logo((210, 88))
    if logo is not None:
        image.paste(logo, (76, 48), logo)
        logo_drawn = True

    if not logo_drawn:
        draw.text((92, 68), "ZERO PRECO", font=brand_font, fill="#ffffff")

    site_label = "zeropreco.com.br"
    site_bbox = draw.textbbox((0, 0), site_label, font=site_font)
    site_text_width = site_bbox[2] - site_bbox[0]
    site_text_height = site_bbox[3] - site_bbox[1]
    site_text_x = site_badge_box[0] + ((site_badge_box[2] - site_badge_box[0] - site_text_width) / 2)
    site_text_y = site_badge_box[1] + ((site_badge_box[3] - site_badge_box[1] - site_text_height) / 2) - 4
    draw.text((site_text_x, site_text_y), site_label, font=site_font, fill="#4d1d95")

    product_image = _contain_remote_product_image(offer.get("imagem_url"), (860, 650))
    if product_image is not None:
        image.paste(product_image, (110, 196))
    else:
        draw.rounded_rectangle((110, 196, 970, 846), radius=28, fill="#f7f4ef")

    layout = _offer_layout_data(offer)
    current_price_text = layout["current_price_text"]
    old_price_text = layout["old_price_text"]
    pix_price_text = layout["pix_price_text"]
    discount = layout["discount"]
    variant = layout["variant"]

    hero_box = (606, 696, 992, 844)
    draw.rounded_rectangle(hero_box, radius=36, fill="#40156f")
    draw.rounded_rectangle((hero_box[0] + 12, hero_box[1] + 12, hero_box[2] - 12, hero_box[3] - 12), radius=30, fill="#542193")

    badge_label_map = {
        "deal": "De",
        "payment": "No Pix",
        "trust": "Oferta de hoje",
        "clean": "A partir de",
    }
    main_label = badge_label_map.get(variant, "A partir de")
    label_width = draw.textbbox((0, 0), main_label, font=price_label_font)[2]
    current_font = _fit_font_for_width(draw, current_price_text, max_width=250, start_size=52, min_size=30, bold=True)
    current_width = draw.textbbox((0, 0), current_price_text, font=current_font)[2]

    icon_left = hero_box[0] + 30
    icon_top = hero_box[1] + 44
    draw.ellipse((icon_left, icon_top, icon_left + 60, icon_top + 60), fill="#6d36be")

    text_left = icon_left + 78
    draw.text((text_left, hero_box[1] + 18), main_label, font=price_label_font, fill="#f7d84d")
    draw.text((text_left, hero_box[1] + 44), current_price_text, font=current_font, fill="#ffcb19")

    detail_y = hero_box[1] + 104
    detail_font = _load_font(22, bold=True)
    subdetail_font = _load_font(20, bold=False)

    if variant == "deal":
        old_font = _fit_font_for_width(draw, old_price_text, max_width=180, start_size=24, min_size=18, bold=False)
        old_x = text_left
        draw.text((old_x, detail_y), old_price_text, font=old_font, fill="#e2d7f7")
        old_bbox = draw.textbbox((old_x, detail_y), old_price_text, font=old_font)
        strike_y = (old_bbox[1] + old_bbox[3]) / 2
        draw.line((old_bbox[0], strike_y, old_bbox[2], strike_y), fill="#ffb7b7", width=3)
        if discount > 0:
            discount_text = f"{discount}% OFF"
            discount_font = _fit_font_for_width(draw, discount_text, max_width=120, start_size=24, min_size=18, bold=True)
            pill_box = (hero_box[2] - 148, hero_box[1] + 96, hero_box[2] - 28, hero_box[1] + 132)
            draw.rounded_rectangle(pill_box, radius=18, fill="#ffcb19")
            pill_text_width = draw.textbbox((0, 0), discount_text, font=discount_font)[2]
            draw.text((pill_box[0] + ((pill_box[2] - pill_box[0] - pill_text_width) / 2), pill_box[1] + 4), discount_text, font=discount_font, fill="#40156f")
        draw.text((text_left, detail_y + 30), f"Por {current_price_text}", font=detail_font, fill="#ffffff")
    elif variant == "payment":
        draw.text((text_left, detail_y), pix_price_text, font=detail_font, fill="#ffffff")
        installments = layout["installments"] or ""
        if installments:
            draw.text((text_left, detail_y + 30), installments[:28], font=subdetail_font, fill="#e2d7f7")
    elif variant == "trust":
        shipping = layout["shipping"] or ""
        rating = layout["rating"]
        rating_count = layout["rating_count"]
        if shipping:
            draw.text((text_left, detail_y), shipping[:28], font=detail_font, fill="#ffffff")
        if rating and rating_count:
            draw.text((text_left, detail_y + 30), f"{rating}/5 ({rating_count})", font=subdetail_font, fill="#e2d7f7")
        elif rating:
            draw.text((text_left, detail_y + 30), f"{rating}/5", font=subdetail_font, fill="#e2d7f7")
    else:
        promo = layout["promo"] or ""
        if promo:
            draw.text((text_left, detail_y), promo[:28], font=subdetail_font, fill="#e2d7f7")

    chip_y = 848
    for chip in layout["badges"]:
        chip_text = chip
        chip_font = _fit_font_for_width(draw, chip_text, max_width=892, start_size=22, min_size=17, bold=True)
        chip_bbox = draw.textbbox((0, 0), chip_text, font=chip_font)
        chip_width = chip_bbox[2] - chip_bbox[0]
        chip_box = (94, chip_y, min(986, 94 + chip_width + 48), chip_y + 42)
        draw.rounded_rectangle(chip_box, radius=20, fill="#eef3ff")
        draw.text((chip_box[0] + 22, chip_box[1] + 7), chip_text, font=chip_font, fill="#26416b")
        chip_y += 50

    title_lines = []
    current = []
    for word in str(offer["titulo"]).split():
        trial = " ".join(current + [word]).strip()
        if len(trial) <= 32:
            current.append(word)
        else:
            if current:
                title_lines.append(" ".join(current))
            current = [word]
    if current:
        title_lines.append(" ".join(current))
    title_lines = title_lines[:3]

    y = max(886, chip_y + 14)
    for line in title_lines:
        text_width = draw.textbbox((0, 0), line, font=title_font)[2]
        draw.text(((1080 - text_width) / 2, y), line, font=title_font, fill="#202124")
        y += 46

    image.save(destination, format="JPEG", quality=92, optimize=True)
    return {
        "ok": True,
        "offer_id": offer["id"],
        "filename": filename,
        "file_path": str(destination),
        "public_url": story_public_url(filename),
    }
