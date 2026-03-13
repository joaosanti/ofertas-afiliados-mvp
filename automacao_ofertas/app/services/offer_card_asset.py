from io import BytesIO
from pathlib import Path
from typing import Any

import httpx
import re
from PIL import Image, ImageDraw, ImageFont, ImageOps

from app.services.sftp_deploy import ensure_stories_dir, story_public_url


PROJECT_ROOT = Path(__file__).resolve().parents[3]
ZERO_PRECO_LOGO = PROJECT_ROOT / "public_html" / "assets" / "img" / "logo-zp.png"


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
            ]
        )
    candidates.extend(
        [
            r"C:\Windows\Fonts\arial.ttf",
            r"C:\Windows\Fonts\segoeui.ttf",
            r"C:\Windows\Fonts\calibri.ttf",
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
        with httpx.Client(timeout=25, follow_redirects=True) as client:
            response = client.get(image_url)
            response.raise_for_status()
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


def generate_offer_square_card_asset(offer: dict[str, Any], *, suffix: str = "card") -> dict[str, Any]:
    filename = f"offer-{offer['id']}-{_slugify(offer['slug'])}-{suffix}.jpg"
    destination = ensure_stories_dir() / filename

    image = Image.new("RGB", (1080, 1080), "#efe9df")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 1080, 1080), fill="#efe9df")

    draw.rounded_rectangle((42, 36, 1038, 1040), radius=40, fill="#ffffff")
    draw.rounded_rectangle((42, 36, 1038, 162), radius=40, fill="#4d1d95")
    draw.rectangle((42, 118, 1038, 162), fill="#4d1d95")
    draw.rounded_rectangle((662, 52, 980, 146), radius=46, fill="#ffcb19")

    brand_font = _load_font(42, bold=True)
    title_font = _load_font(36, bold=True)
    price_font = _load_font(48, bold=True)
    price_label_font = _load_font(18, bold=True)
    site_font = _load_font(28, bold=True)

    logo_drawn = False
    if ZERO_PRECO_LOGO.exists():
        try:
            logo = Image.open(ZERO_PRECO_LOGO).convert("RGBA")
            logo.thumbnail((248, 90))
            image.paste(logo, (78, 54), logo)
            logo_drawn = True
        except Exception:
            logo_drawn = False

    if not logo_drawn:
        draw.text((92, 68), "ZERO PRECO", font=brand_font, fill="#ffffff")

    draw.text((706, 84), "zeropreco.com.br", font=site_font, fill="#4d1d95")

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
