"""Posters for LinkedIn posts, drawn with Pillow so no browser or paid service is needed.

Three layouts, all 1080x1350 (4:5), the portrait size that takes the most room in the feed:
  points     a headline and 2-5 numbered points
  stat       one big number with what it means
  statement  one strong sentence

Drawn at twice the size and scaled down, which keeps the edges of shapes smooth.
"""

import io
import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_FILE = Path(__file__).resolve().parents[2] / "assets" / "fonts" / "Inter.ttf"
W, H = 1080, 1350
SCALE = 2
TEMPLATES = ("points", "stat", "statement")

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


@dataclass
class Brand:
    name: str = "Codevryn"
    website: str = ""
    primary: str = "#F5F8FC"  # background
    accent: str = "#1E3A5F"
    logo: bytes | None = None


def rgb(value: str, fallback: str) -> tuple[int, int, int]:
    found = HEX.match(value.strip()) or HEX.match(fallback)
    h = found.group(1)  # type: ignore[union-attr]
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def luminance(c: tuple[int, int, int]) -> float:
    def f(v: int) -> float:
        v /= 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def font(size: float, weight: int = 400) -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(str(FONT_FILE), round(size * SCALE))
    f.set_variation_by_axes([32 if size >= 30 else 14, weight])  # optical size, weight
    return f


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont, max_width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.split("\n"):
        line = ""
        for word in paragraph.split():
            trial = f"{line} {word}".strip()
            if draw.textlength(trial, font=f) <= max_width * SCALE or not line:
                line = trial
            else:
                lines.append(line)
                line = word
        lines.append(line)
    return [ln for ln in lines if ln] or [""]


def fit(draw, text: str, max_width: float, max_height: float, sizes: range, weight: int, line_gap: float, max_lines: int):
    """The largest font size at which the text fits the box. Returns (font, lines, size)."""
    for size in sizes:
        f = font(size, weight)
        lines = wrap(draw, text, f, max_width)
        if len(lines) <= max_lines and len(lines) * size * line_gap <= max_height:
            return f, lines, size
    size = sizes[-1]
    f = font(size, weight)
    return f, wrap(draw, text, f, max_width)[:max_lines], size


def draw_lines(draw, x, y, lines, f, fill, size, line_gap, anchor="la", width=None):
    for i, line in enumerate(lines):
        px = x
        if anchor == "ma" and width:
            px = x + width / 2
        draw.text((px * SCALE, (y + i * size * line_gap) * SCALE), line, font=f, fill=fill, anchor=anchor)
    return y + len(lines) * size * line_gap


def background(brand: Brand) -> tuple[Image.Image, tuple, tuple, tuple]:
    base = rgb(brand.primary, "#0B1220")
    accent = rgb(brand.accent, "#3B82F6")
    dark = luminance(base) < 0.4
    text = (248, 250, 252) if dark else (15, 23, 42)
    muted = mix(text, base, 0.35 if dark else 0.4)
    top = mix(base, accent, 0.10) if dark else mix(base, (255, 255, 255), 0.0)
    img = Image.new("RGB", (W * SCALE, H * SCALE), base)
    px = ImageDraw.Draw(img)
    for y in range(0, H * SCALE, 4):  # vertical gradient
        t = y / (H * SCALE)
        px.rectangle([0, y, W * SCALE, y + 4], fill=mix(top, base, min(1, t * 1.4)))
    glow = Image.new("RGB", img.size, (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([(W - 420) * SCALE, -300 * SCALE, (W + 380) * SCALE, 500 * SCALE], fill=mix((0, 0, 0), accent, 0.55))
    gd.ellipse([-380 * SCALE, (H - 360) * SCALE, 420 * SCALE, (H + 380) * SCALE], fill=mix((0, 0, 0), accent, 0.28))
    glow = glow.filter(ImageFilter.GaussianBlur(170 * SCALE / 2))
    if dark:
        from PIL import ImageChops

        img = ImageChops.add(img, glow)
    else:
        img = Image.blend(img, glow, 0.08)
    # Fine dot grid, barely visible, so a flat background does not look empty.
    dots = ImageDraw.Draw(img, "RGBA")
    dot = (*text, 14)
    for gx in range(60, W, 60):
        for gy in range(60, H, 60):
            dots.ellipse([(gx - 1.5) * SCALE, (gy - 1.5) * SCALE, (gx + 1.5) * SCALE, (gy + 1.5) * SCALE], fill=dot)
    return img, text, muted, accent


def logo_of(brand: Brand) -> Image.Image | None:
    """The logo exactly as uploaded (colours untouched), or None when there is none or it cannot be read."""
    if not brand.logo:
        return None
    try:
        return Image.open(io.BytesIO(brand.logo)).convert("RGBA")
    except OSError:
        return None


def paste_logo(img: Image.Image, brand: Brand) -> None:
    """Put the logo on the finished poster at its final size, so it is not resampled twice.

    On a dark background it sits on a white plate: a logo drawn for light backgrounds is never recoloured.
    """
    logo = logo_of(brand)
    if logo is None:
        return
    box = logo.getchannel("A").getbbox()  # trim the empty margin so the logo lines up with the text below it
    if box:
        logo = logo.crop(box)
    height = 64
    width = round(logo.width * height / logo.height)
    if width > 300:
        width, height = 300, round(logo.height * 300 / logo.width)
    logo = logo.resize((width, height), Image.LANCZOS)
    x, cy = 72, 70 + 32
    if luminance(rgb(brand.primary, "#0B1220")) < 0.4:
        plate = ImageDraw.Draw(img, "RGBA")
        plate.rounded_rectangle([x - 16, cy - height / 2 - 12, x + width + 16, cy + height / 2 + 12], radius=18, fill=(255, 255, 255, 255))
    img.paste(logo, (x, round(cy - height / 2)), logo)


def header(img: Image.Image, draw: ImageDraw.ImageDraw, brand: Brand, kicker: str, text, muted, accent) -> None:
    """Logo (or the name as a wordmark) on the left, the topic label on the right."""
    y = 70
    x = 72
    if not logo_of(brand):
        # No logo: the first letter in a badge and the name as a wordmark.
        mark = font(30, 800)
        letter = (brand.name.strip()[:1] or "C").upper()
        draw.rounded_rectangle([x * SCALE, y * SCALE, (x + 64) * SCALE, (y + 64) * SCALE], radius=16 * SCALE, fill=accent)
        on_accent = (255, 255, 255) if luminance(accent) < 0.45 else (15, 23, 42)
        draw.text(((x + 32) * SCALE, (y + 33) * SCALE), letter, font=mark, fill=on_accent, anchor="mm")
        draw.text(((x + 82) * SCALE, (y + 33) * SCALE), brand.name, font=font(30, 700), fill=text, anchor="lm")
    if kicker:
        f = font(22, 700)
        label = kicker.upper()
        w = draw.textlength(label, font=f) / SCALE + 44
        x1 = W - 72
        solid = (0, 0, 0, 120) if luminance(text) > 0.5 else (255, 255, 255, 215)  # keeps the label readable over the glow
        draw.rounded_rectangle([(x1 - w) * SCALE, (y + 12) * SCALE, x1 * SCALE, (y + 52) * SCALE], radius=20 * SCALE, fill=solid, outline=accent, width=2 * SCALE)
        draw.text(((x1 - w / 2) * SCALE, (y + 32.5) * SCALE), label, font=f, fill=accent, anchor="mm")


def footer(draw: ImageDraw.ImageDraw, brand: Brand, text, muted, accent, note: str = "") -> None:
    y = H - 84
    draw.line([72 * SCALE, (y - 28) * SCALE, (W - 72) * SCALE, (y - 28) * SCALE], fill=(*muted, 90), width=1 * SCALE)
    left = brand.website or brand.name
    draw.text((72 * SCALE, y * SCALE), left, font=font(26, 600), fill=text, anchor="lm")
    if note:
        draw.text(((W - 72) * SCALE, y * SCALE), note, font=font(24, 500), fill=muted, anchor="rm")


def render_points(spec: dict, brand: Brand) -> Image.Image:
    img, text, muted, accent = background(brand)
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, brand, spec.get("kicker", ""), text, muted, accent)
    points = [p for p in spec.get("points", []) if p.get("title")][:5] or [{"title": spec.get("headline", ""), "text": ""}]
    left, width = 72, W - 144

    # Cards first, so the headline can take whatever height is left. Tighter settings are tried until it all fits.
    card_gap = 22
    pad_x = 34
    text_x_offset = 112
    bottom = H - 150
    top_limit = 200
    for pad_y, body_lines, body_size in ((30, 3, 28), (26, 2, 28), (22, 2, 26), (18, 2, 25)):
        cards = []
        for p in points:
            tf = font(36, 750)
            bf = font(body_size, 450)
            t_lines = wrap(draw, p["title"], tf, width - text_x_offset - pad_x)[:2]
            b_lines = wrap(draw, p.get("text", ""), bf, width - text_x_offset - pad_x)[:body_lines] if p.get("text") else []
            h = pad_y * 2 + len(t_lines) * 36 * 1.2 + (len(b_lines) * body_size * 1.38 + 10 if b_lines else 0)
            cards.append((t_lines, b_lines, h, tf, bf))
        cards_h = sum(c[2] for c in cards) + card_gap * (len(cards) - 1)
        if bottom - cards_h - 50 - top_limit >= 170:
            break
    headline_max_h = max(150, bottom - cards_h - 50 - top_limit)
    hf, h_lines, h_size = fit(draw, spec.get("headline", ""), width, headline_max_h, range(84, 47, -2), 800, 1.08, 4)
    y = top_limit
    y = draw_lines(draw, left, y, h_lines, hf, text, h_size, 1.08)
    draw.rounded_rectangle([left * SCALE, (y + 14) * SCALE, (left + 120) * SCALE, (y + 22) * SCALE], radius=4 * SCALE, fill=accent)
    y += 56
    # Spread the cards over the free space, but never past 34px gaps.
    free = bottom - y - cards_h
    gap = min(34, max(card_gap, free / max(1, len(cards) - 1))) if len(cards) > 1 else 0
    for i, (t_lines, b_lines, h, tf, bf) in enumerate(cards):
        card = (255, 255, 255, 235) if luminance(text) < 0.5 else (*text, 15)  # white cards on a light poster
        draw.rounded_rectangle([left * SCALE, y * SCALE, (left + width) * SCALE, (y + h) * SCALE], radius=26 * SCALE, fill=card, outline=(*text, 28), width=1 * SCALE)
        cy = y + h / 2
        draw.ellipse([(left + 30) * SCALE, (cy - 30) * SCALE, (left + 90) * SCALE, (cy + 30) * SCALE], fill=accent)
        on_accent = (255, 255, 255) if luminance(accent) < 0.45 else (15, 23, 42)
        draw.text(((left + 60) * SCALE, (cy + 1) * SCALE), str(i + 1), font=font(32, 800), fill=on_accent, anchor="mm")
        ty = y + pad_y
        ty = draw_lines(draw, left + text_x_offset, ty, t_lines, tf, text, 36, 1.2)
        if b_lines:
            draw_lines(draw, left + text_x_offset, ty + 8, b_lines, bf, muted, body_size, 1.38)
        y += h + gap
    footer(draw, brand, text, muted, accent, spec.get("footer", ""))
    return img


def render_stat(spec: dict, brand: Brand) -> Image.Image:
    img, text, muted, accent = background(brand)
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, brand, spec.get("kicker", ""), text, muted, accent)
    left, width = 72, W - 144
    stat = str(spec.get("stat", "")).strip() or "—"
    for size in range(330, 90, -10):
        sf = font(size, 850)
        if draw.textlength(stat, font=sf) <= width * SCALE:
            break
    top = 330
    draw.text((left * SCALE, top * SCALE), stat, font=sf, fill=accent, anchor="la")
    y = top + size * 1.12 + 10
    draw.rounded_rectangle([left * SCALE, y * SCALE, (left + 120) * SCALE, (y + 8) * SCALE], radius=4 * SCALE, fill=text)
    y += 50
    lf, l_lines, l_size = fit(draw, spec.get("stat_label", spec.get("headline", "")), width, 330, range(64, 35, -2), 780, 1.15, 4)
    y = draw_lines(draw, left, y, l_lines, lf, text, l_size, 1.15)
    caption = spec.get("caption", "")
    if caption:
        cf, c_lines, c_size = fit(draw, caption, width, 230, range(34, 24, -1), 450, 1.45, 5)
        draw_lines(draw, left, y + 36, c_lines, cf, muted, c_size, 1.45)
    footer(draw, brand, text, muted, accent, spec.get("footer", ""))
    return img


def render_statement(spec: dict, brand: Brand) -> Image.Image:
    img, text, muted, accent = background(brand)
    draw = ImageDraw.Draw(img, "RGBA")
    header(img, draw, brand, spec.get("kicker", ""), text, muted, accent)
    left, width = 72, W - 144
    draw.text((left * SCALE, 250 * SCALE), "“", font=font(260, 800), fill=accent, anchor="la")
    body = spec.get("headline", "")
    f, lines, size = fit(draw, body, width, 640, range(78, 41, -2), 760, 1.2, 9)
    y = draw_lines(draw, left, 500, lines, f, text, size, 1.2)
    caption = spec.get("caption", "")
    if caption:
        draw.rounded_rectangle([left * SCALE, (y + 30) * SCALE, (left + 120) * SCALE, (y + 38) * SCALE], radius=4 * SCALE, fill=accent)
        cf, c_lines, c_size = fit(draw, caption, width, 160, range(32, 24, -1), 450, 1.4, 3)
        draw_lines(draw, left, y + 70, c_lines, cf, muted, c_size, 1.4)
    footer(draw, brand, text, muted, accent, spec.get("footer", ""))
    return img


def render_poster(spec: dict, brand: Brand) -> bytes:
    """PNG bytes of the poster described by `spec`."""
    template = spec.get("template") if spec.get("template") in TEMPLATES else "points"
    img = {"points": render_points, "stat": render_stat, "statement": render_statement}[template](spec, brand)
    img = img.resize((W, H), Image.LANCZOS)
    paste_logo(img, brand)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
