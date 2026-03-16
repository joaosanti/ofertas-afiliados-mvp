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
    price_font = _load_font(48, bold=True)
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

    draw.rounded_rectangle((628, 708, 978, 810), radius=30, fill="#40156f")
    draw.rounded_rectangle((640, 718, 966, 800), radius=26, fill="#542193")
    draw.ellipse((654, 732, 718, 792), fill="#6d36be")
    draw.text((740, 734), "A partir de", font=price_label_font, fill="#f7d84d")
    draw.text((740, 752), _money(offer["preco"]), font=price_font, fill="#ffcb19")

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

    y = 886
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
