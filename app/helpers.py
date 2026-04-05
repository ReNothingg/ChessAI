import os

from PIL import Image, ImageDraw, ImageFont, ImageTk

from config import ASSETS_DIR, SQUARE_SIZE


def ensure_assets_exist() -> bool:
    return os.path.isdir(ASSETS_DIR)


def make_placeholder_piece(symbol: str, size: int = SQUARE_SIZE) -> ImageTk.PhotoImage:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", size // 2)
    except Exception:
        font = ImageFont.load_default()

    try:
        bbox = draw.textbbox((0, 0), symbol, font=font)
        width, height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        try:
            width, height = font.getsize(symbol)
        except Exception:
            width, height = size // 2, size // 2

    draw.rectangle([(0, 0), (size, size)], fill=(240, 240, 240, 255))
    draw.text(((size - width) / 2, (size - height) / 2), symbol, font=font, fill="black")
    return ImageTk.PhotoImage(img)
