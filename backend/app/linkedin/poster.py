"""Posters for LinkedIn posts, drawn with Pillow so no browser or paid service is needed.

They are meant to look like a person on a marketing team made them, not like a template engine did: flat paper colours,
a serif or a plain sans headline, a highlighter swipe or a hand-drawn underline on the key words, ticks and circles drawn
with a slightly shaky hand, sticky notes and sheets with a little tilt, a shadow and a strip of tape, and a fine paper grain.
Every poster gets its own mix of these (picked from what it says, so redrawing it gives the same result).

Five layouts, each with two looks, all 1080x1350 (4:5), the portrait size that takes the most room in the feed:
  points     a headline and 2-5 points (a ruled list, or sticky notes)
  checklist  a headline and ticked items (hand-drawn boxes, or a taped sheet)
  compare    the common way against the better way (crossed out, or on a note)
  stat       one big number with what it means (circled, or on a note)
  statement  one strong sentence (on the page, or on a taped sheet)
  flow       3-5 steps in order, joined by a hand-drawn path (a winding path, or a ladder of boxes with arrows)
  grid       2-4 parallel ideas as cards (a 2-column grid of notes, or ruled columns with big hand-drawn numerals)

Drawn at twice the size and scaled down, which keeps the edges of shapes smooth.
"""

import io
import math
import random
import re
import zlib
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"
FONT_FILE = FONT_DIR / "Inter.ttf"
W, H = 1080, 1350
SCALE = 2
TEMPLATES = ("points", "stat", "statement", "compare", "checklist", "flow", "grid")

HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")

INK = (15, 23, 42)  # text on paper-coloured notes, whatever the poster's own colours are
INK_SOFT = (71, 85, 105)
PASTELS = ((255, 236, 150), (255, 210, 186), (198, 234, 210), (204, 222, 250), (240, 216, 246))
MARKER = (255, 226, 110)  # a yellow highlighter, used on light posters


@dataclass
class Brand:
    name: str = "Codevryn"
    website: str = ""
    primary: str = "#F5F8FC"  # background
    accent: str = "#1E3A5F"
    logo: bytes | None = None
    # "personal": a person's poster. No logo, no website, a round avatar with the name and a line about what they do.
    style: str = "company"
    tagline: str = ""


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


def contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """WCAG contrast ratio, 1 to 21. Body text needs 4.5 or more."""
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def on_color(fill: tuple[int, int, int]) -> tuple[int, int, int]:
    """White or near-black text, whichever reads better on `fill`."""
    white, ink = (255, 255, 255), (15, 23, 42)
    return white if contrast(white, fill) >= contrast(ink, fill) else ink


def readable_muted(text: tuple[int, int, int], base: tuple[int, int, int]) -> tuple[int, int, int]:
    """The softer text colour for small print: as quiet as it can be while still passing 4.5:1 on the background."""
    for t in (0.30, 0.25, 0.20, 0.15, 0.10, 0.05):
        c = mix(text, base, t)
        if contrast(c, base) >= 4.5:
            return c
    return text


# (background, accent) pairs for a person's posters, each checked for readable contrast (see tests). Mostly warm paper tones with
# one ink-like accent, as a designer would pick, plus a few dark ones. A company keeps its brand colours; a person's posters
# rotate through these so the feed does not show the same colours every day.
PERSONAL_THEMES: tuple[tuple[str, str], ...] = (
    ("#F4EFE6", "#B4421F"),  # kraft paper, terracotta
    ("#FBF7F0", "#0F5C4D"),  # cream, deep green
    ("#EEF2F7", "#2B4BA8"),  # cool grey, cobalt
    ("#FFFFFF", "#C2410C"),  # white, orange
    ("#F7F1E8", "#6B2D5C"),  # linen, plum
    ("#E9EEE6", "#2F5D3A"),  # sage, forest
    ("#FAF3E3", "#9A3412"),  # butter paper, rust
    ("#F1ECF6", "#5B3FA8"),  # lilac paper, violet
    ("#14213D", "#FCA311"),  # navy, amber
    ("#1B1B1B", "#FF7A59"),  # charcoal, coral
    ("#0F2A2A", "#F2C14E"),  # deep teal, gold
)


def personal_theme(spec: dict) -> tuple[str, str]:
    """The colours for one personal poster. Picked from what the poster says, so the same post always looks the same
    when it is redrawn, while different posts get different colours."""
    key = f"{spec.get('template', '')}|{spec.get('headline', '')}|{spec.get('stat', '')}".encode()
    return PERSONAL_THEMES[zlib.crc32(key) % len(PERSONAL_THEMES)]


@dataclass(frozen=True)
class Look:
    """The art direction of one poster: headline typeface, which of the two layouts, how the key words are marked."""

    face: str  # "serif" or "sans"
    weight: int
    variant: int  # 0 or 1
    mark: str  # "marker" (highlighter), "underline" (hand-drawn)
    seed: int


def look_of(spec: dict) -> Look:
    key = f"look|{spec.get('template', '')}|{spec.get('headline', '')}|{spec.get('stat', '')}|{spec.get('kicker', '')}".encode()
    h = zlib.crc32(key)
    serif = bool((h >> 5) & 1)
    return Look(
        face="serif" if serif else "sans",
        weight=620 if serif else 800,
        variant=(h >> 4) & 1,
        mark=("marker", "underline", "marker")[(h >> 2) % 3],
        seed=h,
    )


@lru_cache(maxsize=512)
def font(size: float, weight: int = 400, face: str = "sans") -> ImageFont.FreeTypeFont:
    px = round(size * SCALE)
    if face == "serif":
        f = ImageFont.truetype(str(FONT_DIR / "Fraunces.ttf"), px)
        f.set_variation_by_axes([min(144, max(9, size)), weight, 30, 0])  # optical size, weight, softness, wonk
    elif face == "hand":
        f = ImageFont.truetype(str(FONT_DIR / "Caveat.ttf"), px)
        f.set_variation_by_axes([min(700, max(400, weight))])
    else:
        f = ImageFont.truetype(str(FONT_FILE), px)
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


def fit(draw, text: str, max_width: float, max_height: float, sizes: range, weight: int, line_gap: float, max_lines: int, face: str = "sans"):
    """The largest font size at which the text fits the box. Returns (font, lines, size)."""
    for size in sizes:
        f = font(size, weight, face)
        lines = wrap(draw, text, f, max_width)
        if len(lines) <= max_lines and len(lines) * size * line_gap <= max_height:
            return f, lines, size
    size = sizes[-1]
    f = font(size, weight, face)
    return f, wrap(draw, text, f, max_width)[:max_lines], size


def draw_lines(draw, x, y, lines, f, fill, size, line_gap, anchor="la", width=None):
    for i, line in enumerate(lines):
        px = x
        if anchor == "ma" and width:
            px = x + width / 2
        draw.text((px * SCALE, (y + i * size * line_gap) * SCALE), line, font=f, fill=fill, anchor=anchor)
    return y + len(lines) * size * line_gap


# ---------------------------------------------------------------------------------------------------------------------
# Hand-made marks. Coordinates are in poster pixels (1080 wide); the helpers scale them to the drawing canvas.
# ---------------------------------------------------------------------------------------------------------------------


def stroke(d, pts, color, width, rng, wobble=1.4):
    """A pen line through `pts` that is not perfectly straight, with round ends."""
    out = []
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        n = max(2, int(math.hypot(x1 - x0, y1 - y0) / 34))
        for i in range(n):
            t = i / n
            out.append((x0 + (x1 - x0) * t + rng.uniform(-wobble, wobble), y0 + (y1 - y0) * t + rng.uniform(-wobble, wobble)))
    out.append(pts[-1])
    sc = [(x * SCALE, y * SCALE) for x, y in out]
    d.line(sc, fill=color, width=round(width * SCALE), joint="curve")
    r = width * SCALE / 2
    for x, y in (sc[0], sc[-1]):
        d.ellipse([x - r, y - r, x + r, y + r], fill=color)


def squiggle(d, x0, x1, y, color, width, rng):
    """A hand-drawn underline: a gentle wave that drifts a little."""
    drift = rng.uniform(-3, 3)
    pts = [(x, y + math.sin((x - x0) / 23) * 2.4 + drift * (x - x0) / max(1, x1 - x0)) for x in range(int(x0), int(x1), 9)]
    pts.append((x1, y + drift))
    stroke(d, pts, color, width, rng, wobble=0.7)


def hand_circle(d, box, color, width, rng):
    """An ellipse drawn in one go with a pen: it overshoots and does not quite close."""
    x0, y0, x1, y1 = box
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    start = rng.uniform(-0.9, -0.3)
    total = math.pi * 2 * 1.1
    phase = rng.uniform(0, 6)
    n = 70
    pts = []
    for i in range(n + 1):
        t = start + total * i / n
        k = 1 + 0.035 * math.sin(3 * t + phase) + 0.06 * (i / n) + rng.uniform(-0.006, 0.006)
        pts.append((cx + rx * k * math.cos(t), cy + ry * k * math.sin(t)))
    stroke(d, pts, color, width, rng, wobble=0.5)


def tick(d, x, y, size, color, rng, width=6):
    stroke(d, [(x, y + size * 0.5), (x + size * 0.36, y + size * 0.95), (x + size * 1.12, y - size * 0.15)], color, width, rng, wobble=0.8)


def checkbox(d, x, y, size, color, rng, width=3.5):
    j = lambda: rng.uniform(-1.5, 1.5)  # noqa: E731
    s = size
    pts = [(x + j(), y + j()), (x + s + j(), y + 2 + j()), (x + s - 2 + j(), y + s + j()), (x + 2 + j(), y + s - 2 + j()), (x + 1, y + 3)]
    stroke(d, pts, color, width, rng, wobble=0.6)


def arrow(d, x0, x1, y, color, rng, width=4):
    stroke(d, [(x0, y + 1), (x1, y - 1)], color, width, rng, wobble=0.7)
    stroke(d, [(x1 - 17, y - 14), (x1, y - 1), (x1 - 15, y + 13)], color, width, rng, wobble=0.5)


def marker(d, x0, y0, x1, y1, color, rng):
    """A highlighter swipe: slightly slanted ends and uneven edges."""
    j = lambda: rng.uniform(-2.5, 2.5)  # noqa: E731
    pts = [(x0 - 8 + j(), y0 + 4 + j()), (x1 + 6 + j(), y0 - 1 + j()), (x1 + 10 + j(), y1 + j()), (x0 - 4 + j(), y1 + 3 + j())]
    d.polygon([(x * SCALE, y * SCALE) for x, y in pts], fill=color)


def paper(img, size, center, angle, fill, draw_fn, tape=True, tape_x=0.5):
    """A sheet or sticky note with a soft shadow and a strip of tape, tilted by `angle` degrees.

    `draw_fn(draw, ox, oy)` draws the content; (ox, oy) is the sheet's top-left corner, in poster pixels, on the sheet's own canvas.
    """
    w, h = size
    pad = 48
    lw, lh = round((w + pad * 2) * SCALE), round((h + pad * 2) * SCALE)
    shadow = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([pad * SCALE + 4, pad * SCALE + 14, (pad + w) * SCALE + 4, (pad + h) * SCALE + 14], radius=6 * SCALE, fill=(0, 0, 0, 105))
    shadow = shadow.filter(ImageFilter.GaussianBlur(11 * SCALE))
    sheet = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    d = ImageDraw.Draw(sheet, "RGBA")
    d.rounded_rectangle([pad * SCALE, pad * SCALE, (pad + w) * SCALE, (pad + h) * SCALE], radius=5 * SCALE, fill=(*fill, 255))
    draw_fn(d, pad, pad)
    if tape:
        tx = pad + w * tape_x
        d.polygon(
            [((tx - 66) * SCALE, (pad - 12) * SCALE), ((tx + 64) * SCALE, (pad - 17) * SCALE), ((tx + 68) * SCALE, (pad + 24) * SCALE), ((tx - 62) * SCALE, (pad + 28) * SCALE)],
            fill=(236, 226, 190, 190),
        )
    layer = Image.alpha_composite(shadow, sheet).rotate(angle, resample=Image.BICUBIC, expand=True)
    img.paste(layer, (round(center[0] * SCALE - layer.width / 2), round(center[1] * SCALE - layer.height / 2)), layer)


def mark_color(base, accent, dark: bool):
    return mix(base, accent, 0.42) if dark else MARKER


def draw_headline(draw, text, x, y, width, max_h, sizes, look: Look, ink, accent, base, rng, max_lines, gap=1.1, face=None, weight=None, marked=True):
    """The headline in the poster's typeface with its key words marked like a person would mark them. Returns the y below it."""
    face = face or look.face
    weight = weight or look.weight
    f, lines, size = fit(draw, text, width, max_h, sizes, weight, gap, max_lines, face)
    words = [w for ln in lines for w in ln.split()]
    dark = luminance(base) < 0.4
    n = 0 if not marked or len(words) < 4 else (2 if len(words) < 9 else 3)
    chosen: set[int] = set()
    if n:
        # The run of words with the most letters: that is where the meaning is, not on "the" or "it".
        best = max(range(len(words) - n + 1), key=lambda i: (sum(len(re.sub(r"\W", "", w)) for w in words[i : i + n]), i))
        chosen = set(range(best, best + n))
    color = mark_color(base, accent, dark)
    idx = 0
    for li, line in enumerate(lines):
        ws = line.split()
        run = [k for k in range(len(ws)) if idx + k in chosen]
        if run:
            before = draw.textlength(" ".join(ws[: run[0]]) + (" " if run[0] else ""), font=f) / SCALE
            upto = draw.textlength(" ".join(ws[: run[-1] + 1]), font=f) / SCALE
            ly = y + li * size * gap
            if look.mark == "marker":
                marker(draw, x + before, ly + size * 0.3, x + upto, ly + size * 1.08, color, rng)
            else:
                squiggle(draw, x + before, x + upto, ly + size * 1.12, accent, max(4, size / 14), rng)
        idx += len(ws)
    return draw_lines(draw, x, y, lines, f, ink, size, gap)


# ---------------------------------------------------------------------------------------------------------------------
# Page furniture
# ---------------------------------------------------------------------------------------------------------------------


def background(brand: Brand) -> tuple[Image.Image, tuple, tuple, tuple]:
    """Flat paper in the poster's own colour. No gradient, no glow: the grain is added once the poster is finished."""
    base = rgb(brand.primary, "#0B1220")
    accent = rgb(brand.accent, "#3B82F6")
    dark = luminance(base) < 0.4
    text = (248, 250, 252) if dark else (15, 23, 42)
    muted = readable_muted(text, base)
    return Image.new("RGB", (W * SCALE, H * SCALE), base), text, muted, accent


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


def header(img: Image.Image, draw: ImageDraw.ImageDraw, brand: Brand, kicker: str, text, muted, accent, rng) -> None:
    """Logo (or the name as a wordmark) on the left, the topic written by hand on the right."""
    y = 70
    x = 72
    if not logo_of(brand) and brand.name.strip():
        # No logo: the first letter in a badge and the name as a wordmark. A person gets a round avatar, a company a square one.
        mark = font(30, 800)
        letter = brand.name.strip()[:1].upper()
        box = [x * SCALE, y * SCALE, (x + 64) * SCALE, (y + 64) * SCALE]
        if brand.style == "personal":
            draw.ellipse(box, fill=accent)
        else:
            draw.rounded_rectangle(box, radius=16 * SCALE, fill=accent)
        on_accent = on_color(accent)
        draw.text(((x + 32) * SCALE, (y + 33) * SCALE), letter, font=mark, fill=on_accent, anchor="mm")
        if brand.style == "personal" and brand.tagline:
            draw.text(((x + 82) * SCALE, (y + 18) * SCALE), brand.name, font=font(28, 700), fill=text, anchor="lm")
            draw.text(((x + 82) * SCALE, (y + 48) * SCALE), brand.tagline, font=font(21, 500), fill=muted, anchor="lm")
        else:
            draw.text(((x + 82) * SCALE, (y + 33) * SCALE), brand.name, font=font(30, 700), fill=text, anchor="lm")
    if kicker:
        f = font(44, 700, "hand")
        label = kicker.strip()
        tw = draw.textlength(label, font=f) / SCALE
        pad = 26
        lw, lh = round((tw + pad * 2) * SCALE), round(86 * SCALE)
        layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer, "RGBA")
        ld.text((pad * SCALE, 32 * SCALE), label, font=f, fill=(*accent, 255), anchor="lm")
        squiggle(ld, pad, pad + tw, 60, accent, 3.2, rng)
        layer = layer.rotate(2.5, resample=Image.BICUBIC, expand=True)
        img.paste(layer, (round((W - 72) * SCALE - layer.width + pad * SCALE * 0.6), round((y + 4) * SCALE)), layer)


def aside_note(img: Image.Image, text: str, accent, rng) -> None:
    """A short note in the author's own handwriting at the bottom left, slightly tilted, like something jotted on the print."""
    f = font(46, 700, "hand")
    probe = ImageDraw.Draw(img)
    tw = probe.textlength(text, font=f) / SCALE
    pad = 14
    layer = Image.new("RGBA", (round((tw + pad * 2) * SCALE), round(80 * SCALE)), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer, "RGBA")
    ld.text((pad * SCALE, 40 * SCALE), text, font=f, fill=(*accent, 255), anchor="lm")
    layer = layer.rotate(rng.uniform(1.5, 3.5), resample=Image.BICUBIC, expand=True)
    img.paste(layer, (round(60 * SCALE), round((H - 150) * SCALE)), layer)


def footer(draw: ImageDraw.ImageDraw, brand: Brand, text, muted, accent, note: str = "") -> None:
    y = H - 84
    # A personal poster carries no website and no company: only the person, already shown at the top, so the line stays quiet.
    left = "" if brand.style == "personal" else (brand.website or brand.name)
    if not left and not note:
        return
    draw.line([72 * SCALE, (y - 28) * SCALE, (W - 72) * SCALE, (y - 28) * SCALE], fill=(*muted, 90), width=1 * SCALE)
    if left:
        draw.text((72 * SCALE, y * SCALE), left, font=font(26, 600), fill=text, anchor="lm")
    if note:
        draw.text(((W - 72) * SCALE, y * SCALE), note, font=font(24, 500), fill=muted, anchor="rm")


@dataclass
class Page:
    img: Image.Image
    draw: ImageDraw.ImageDraw
    text: tuple
    muted: tuple
    accent: tuple
    base: tuple
    look: Look
    rng: random.Random
    brand: Brand
    blank: Image.Image | None = None  # the page before any content, to find where the content is


def decorate(p: "Page") -> None:
    """A large soft circle and a thin ring in the bottom-right corner, drawn behind the content (only on empty paper, so cards
    and their shadows are never touched): depth without clutter. Solid colours mixed from the paper, so it is never muddy."""
    dark = luminance(p.base) < 0.4
    layer = p.blank.copy()
    d = ImageDraw.Draw(layer)
    cx, cy, r = (W - 70) * SCALE, (H - 40) * SCALE, 330 * SCALE
    r2 = 235 * SCALE
    if dark:  # a filled disc turns muddy on dark paper, so two thin rings instead
        ring = mix(p.base, p.accent, 0.35)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=ring, width=3 * SCALE)
        d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=ring, width=3 * SCALE)
    else:
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=mix(p.base, p.accent, 0.11))
        d.ellipse([cx - r2, cy - r2, cx + r2, cy + r2], outline=mix(p.base, p.accent, 0.30), width=3 * SCALE)
    empty = ImageChops.difference(p.img, p.blank).convert("L").point(lambda v: 255 if v <= 3 else 0)
    p.img.paste(layer, (0, 0), empty)


def balance(p: "Page") -> None:
    """Centre the content block (headline and body) between the header and the footer, so the poster is not top-heavy."""
    top_edge, bottom_edge = 190 * SCALE, (H - 120) * SCALE
    diff = ImageChops.difference(p.img, p.blank).convert("L").point(lambda v: 255 if v > 3 else 0)
    diff.paste(0, (0, 0, diff.width, top_edge))
    box = diff.getbbox()
    if not box:
        return
    top, bottom = box[1], box[3]
    shift = max(0, min(round(((top_edge + bottom_edge) - (top + bottom)) / 2), 230 * SCALE))
    if shift < 8 * SCALE:
        return
    region = (0, max(top_edge, top - 4), p.img.width, min(p.img.height, bottom + 4))
    content = p.img.crop(region)
    p.img.paste(p.blank.crop(region), region[:2])
    p.img.paste(content, (region[0], region[1] + shift), diff.crop(region))


def start(spec: dict, brand: Brand) -> Page:
    img, text, muted, accent = background(brand)
    draw = ImageDraw.Draw(img, "RGBA")
    look = look_of(spec)
    rng = random.Random(look.seed)
    base = rgb(brand.primary, "#0B1220")
    header(img, draw, brand, spec.get("kicker", ""), text, muted, accent, rng)
    return Page(img, draw, text, muted, accent, base, look, rng, brand, blank=img.copy())


def finish(p: Page, spec: dict) -> Image.Image:
    balance(p)
    decorate(p)
    footer(p.draw, p.brand, p.text, p.muted, p.accent, spec.get("footer", ""))
    if spec.get("aside") and p.brand.style == "personal":
        aside_note(p.img, spec["aside"], p.accent, p.rng)
    return p.img


def head(p: Page, text: str, y: float, max_h: float, sizes=range(84, 47, -2), max_lines=4, marked=True) -> float:
    return draw_headline(p.draw, text, 72, y, W - 144, max_h, sizes, p.look, p.text, p.accent, p.base, p.rng, max_lines, marked=marked)


def rows_of(spec: dict, limit: int) -> list[dict]:
    return [r for r in spec.get("points", []) if r.get("title")][:limit] or [{"title": spec.get("headline", ""), "text": ""}]


# ---------------------------------------------------------------------------------------------------------------------
# Layouts
# ---------------------------------------------------------------------------------------------------------------------


def render_points(spec: dict, brand: Brand) -> Image.Image:
    p = start(spec, brand)
    draw, look = p.draw, p.look
    points = rows_of(spec, 5)
    left, width = 72, W - 144
    bottom, top_limit = H - 150, 200
    notes = look.variant == 1
    tface, tweight = (look.face, 620 if look.face == "serif" else 750)

    if notes:
        params = ((34, 3, 32, 38), (30, 3, 29, 34), (24, 3, 27, 32), (20, 2, 26, 31), (16, 2, 25, 30), (14, 2, 24, 29))
        text_w = width - 70 - 76
    else:
        params = ((38, 3, 33, 40), (34, 3, 31, 36), (28, 3, 30, 35), (22, 3, 28, 34), (18, 2, 28, 33), (14, 2, 26, 32))
        text_w = width - 112
    gap = 24 if notes else 0
    for pad_y, body_lines, body_size, title_size in params:
        built = []
        tf, bf = font(title_size, tweight, tface), font(body_size, 450)
        for pt in points:
            t_lines = wrap(draw, pt["title"], tf, text_w)[:2]
            b_lines = wrap(draw, pt.get("text", ""), bf, text_w)[:body_lines] if pt.get("text") else []
            h = pad_y * 2 + len(t_lines) * title_size * 1.2 + (len(b_lines) * body_size * 1.38 + 8 if b_lines else 0)
            built.append((t_lines, b_lines, h))
        rows_h = sum(b[2] for b in built) + gap * (len(built) - 1)
        if bottom - rows_h - 40 - top_limit >= 170:
            break
    y = head(p, spec.get("headline", ""), top_limit, max(150, bottom - rows_h - 40 - top_limit)) + 56
    free = bottom - y - rows_h
    spread = min(40 if notes else 30, max(0, free / max(1, len(built)))) if free > 0 else 0

    if not notes:
        for i, (t_lines, b_lines, h) in enumerate(built):
            if i:
                draw.line([left * SCALE, (y - spread / 2) * SCALE, (left + width) * SCALE, (y - spread / 2) * SCALE], fill=(*p.text, 38), width=1 * SCALE)
            draw.text((left * SCALE, (y + pad_y - 8) * SCALE), f"{i + 1}", font=font(78, 700, "hand"), fill=p.accent, anchor="la")
            ty = draw_lines(draw, left + 84, y + pad_y, t_lines, tf, p.text, title_size, 1.2)
            if b_lines:
                draw_lines(draw, left + 84, ty + 8, b_lines, bf, p.muted, body_size, 1.38)
            y += h + spread
    else:
        angles = (-1.3, 1.0, -0.8, 1.4, -1.1)
        shifts = (0, 70, 20, 70, 0)
        for i, (t_lines, b_lines, h) in enumerate(built):
            w = width - 70
            nh = h

            def content(d, ox, oy, t_lines=t_lines, b_lines=b_lines, nh=nh):
                ty = draw_lines(d, ox + 38, oy + pad_y, t_lines, tf, INK, title_size, 1.2)
                if b_lines:
                    draw_lines(d, ox + 38, ty + 8, b_lines, bf, INK_SOFT, body_size, 1.38)

            paper(p.img, (w, nh), (left + shifts[i] + w / 2, y + nh / 2), angles[i % 5], PASTELS[(i + look.seed) % len(PASTELS)], content, tape=True, tape_x=0.18 + 0.64 * ((i * 37 % 10) / 10))
            y += nh + gap + spread
    return finish(p, spec)


def render_checklist(spec: dict, brand: Brand) -> Image.Image:
    p = start(spec, brand)
    draw, look = p.draw, p.look
    items = rows_of(spec, 5)
    left, width = 72, W - 144
    bottom, top_limit = H - 150, 200
    sheet = look.variant == 1
    tface, tweight = look.face, (620 if look.face == "serif" else 750)
    tf, bf = font(38, tweight, tface), font(28, 450)
    text_w = (width - 120 - 76) if sheet else (width - 100)
    built = []
    for it in items:
        t_lines = wrap(draw, it["title"], tf, text_w)[:2]
        b_lines = wrap(draw, it.get("text", ""), bf, text_w)[:2] if it.get("text") else []
        built.append((t_lines, b_lines, len(t_lines) * 38 * 1.2 + (len(b_lines) * 28 * 1.38 + 8 if b_lines else 0) + 44))
    list_h = sum(b[2] for b in built) + (90 if sheet else 0)
    y = head(p, spec.get("headline", ""), top_limit, max(150, bottom - list_h - 40 - top_limit)) + 28
    free = bottom - y - list_h
    extra = max(0, min(60, free / max(1, len(built))))

    def rows(d, ox, oy, ink, soft, rule, tick_color):
        cy = oy
        for i, (t_lines, b_lines, h) in enumerate(built):
            checkbox(d, ox, cy + 8, 46, ink, p.rng)
            tick(d, ox + 9, cy + 15, 26, tick_color, p.rng)
            ty = draw_lines(d, ox + 76, cy + 6, t_lines, tf, ink, 38, 1.2)
            if b_lines:
                draw_lines(d, ox + 76, ty + 6, b_lines, bf, soft, 28, 1.38)
            cy += h + extra
            if i < len(built) - 1:
                d.line([ox * SCALE, (cy - 20 - extra / 2) * SCALE, (ox + text_w + 76) * SCALE, (cy - 20 - extra / 2) * SCALE], fill=rule, width=1 * SCALE)

    if not sheet:
        rows(draw, left, y, p.text, p.muted, (*p.text, 36), p.accent)
    else:
        sh = list_h - 90 + extra * len(built) + 70
        sw = width - 30
        paper(
            p.img, (sw, sh), (left + sw / 2 + 12, y + sh / 2 + 18), -1.1, (255, 252, 244),
            lambda d, ox, oy: rows(d, ox + 60, oy + 50, INK, INK_SOFT, (15, 23, 42, 40), (180, 40, 30)), tape=True, tape_x=0.5,
        )
    return finish(p, spec)


def render_stat(spec: dict, brand: Brand) -> Image.Image:
    p = start(spec, brand)
    draw, look = p.draw, p.look
    left, width = 72, W - 144
    stat = str(spec.get("stat", "")).strip() or "—"
    sface, sweight = (look.face, 700 if look.face == "serif" else 850)
    room = width - (150 if look.variant == 0 else 220)
    for size in range(320, 90, -10):
        sf = font(size, sweight, sface)
        if draw.textlength(stat, font=sf) <= room * SCALE:
            break
    bb = draw.textbbox((0, 0), stat, font=sf, anchor="la")
    sw, sh = (bb[2] - bb[0]) / SCALE, (bb[3] - bb[1]) / SCALE
    label = spec.get("stat_label", spec.get("headline", ""))
    caption = spec.get("caption", "")
    if look.variant == 0:
        top = 300
        x = left + 56
        draw.text((x * SCALE, top * SCALE), stat, font=sf, fill=p.accent if look.face == "serif" else p.text, anchor="la")
        cx0, cy0 = x + bb[0] / SCALE, top + bb[1] / SCALE
        hand_circle(draw, (cx0 - 46, cy0 - 40, cx0 + sw + 46, cy0 + sh + 44), p.accent if look.face == "sans" else p.text, 6, p.rng)
        y = cy0 + sh + 44 + 56
    else:
        note_h = sh + 150
        note_w = sw + 150

        def content(d, ox, oy):
            d.text(((ox + 75 - bb[0] / SCALE) * SCALE, (oy + 75 - bb[1] / SCALE) * SCALE), stat, font=sf, fill=INK, anchor="la")

        top = max(270, (H - note_h) / 2 - 120)
        cy = top + note_h / 2
        paper(p.img, (note_w, note_h), (left + note_w / 2 + 14, cy), -2.2, PASTELS[look.seed % len(PASTELS)], content, tape=True, tape_x=0.3)
        y = top + note_h + 70
    lf, l_lines, l_size = fit(draw, label, width, 300, range(60, 35, -2), 780 if look.face == "sans" else 620, 1.15, 4, look.face)
    y = draw_lines(draw, left, y, l_lines, lf, p.text, l_size, 1.15)
    if caption:
        cf, c_lines, c_size = fit(draw, caption, width, 200, range(32, 24, -1), 450, 1.45, 5)
        draw_lines(draw, left, y + 26, c_lines, cf, p.muted, c_size, 1.45)
    return finish(p, spec)


def render_statement(spec: dict, brand: Brand) -> Image.Image:
    p = start(spec, brand)
    draw, look = p.draw, p.look
    left, width = 72, W - 144
    body = spec.get("headline", "")
    caption = spec.get("caption", "")
    if look.variant == 0:
        draw.text((left * SCALE, 215 * SCALE), "“", font=font(300, 700, "serif"), fill=p.accent, anchor="la")
        y = draw_headline(draw, body, left, 470, width, 660, range(78, 41, -2), look, p.text, p.accent, p.base, p.rng, 9, gap=1.2)
        if caption:
            squiggle(draw, left, left + 130, y + 40, p.accent, 5, p.rng)
            cf, c_lines, c_size = fit(draw, caption, width, 160, range(32, 24, -1), 450, 1.4, 3)
            draw_lines(draw, left, y + 70, c_lines, cf, p.muted, c_size, 1.4)
    else:
        pad = 62
        inner = width - 40 - pad * 2
        f, lines, size = fit(draw, body, inner, 560, range(70, 40, -2), look.weight, 1.2, 8, look.face)
        th = len(lines) * size * 1.2
        sh = th + pad * 2
        sw = width - 40

        def content(d, ox, oy):
            draw_lines(d, ox + pad, oy + pad, lines, f, INK, size, 1.2)

        top = max(250, (H - sh) / 2 - 60)
        paper(p.img, (sw, sh), (left + sw / 2 + 10, top + sh / 2), 1.3, (255, 252, 244), content, tape=True, tape_x=0.72)
        if caption:
            cf, c_lines, c_size = fit(draw, caption, width, 160, range(32, 24, -1), 450, 1.4, 3)
            draw_lines(draw, left, top + sh + 56, c_lines, cf, p.muted, c_size, 1.4)
    return finish(p, spec)


def render_compare(spec: dict, brand: Brand) -> Image.Image:
    """The common approach crossed out on the left, the better one on the right."""
    p = start(spec, brand)
    draw, look = p.draw, p.look
    left, width = 72, W - 144
    rows = rows_of(spec, 4)
    notes = look.variant == 1
    bottom = H - 150
    y = head(p, spec.get("headline", ""), 200, 230, range(76, 47, -2), 3) + 22
    mid = 96
    col_w = (width - mid) / 2
    draw.text((left * SCALE, y * SCALE), "instead of", font=font(40, 600, "hand"), fill=p.muted, anchor="la")
    draw.text(((left + col_w + mid) * SCALE, y * SCALE), "do this", font=font(40, 700, "hand"), fill=p.accent, anchor="la")
    y += 70 if notes else 52
    rface, rweight = look.face, (620 if look.face == "serif" else 700)
    pad = 26
    for size in (40, 38, 36, 34, 32, 30, 28, 26):
        lf, rf = font(size, 450), font(size, rweight, rface)
        built = []
        for r in rows:
            l_lines = wrap(draw, r["title"], lf, col_w - (0 if not notes else 0))[:4]
            r_lines = wrap(draw, r.get("text") or r["title"], rf, col_w - (56 if notes else 0))[:4]
            h = max(len(l_lines), len(r_lines)) * size * 1.3 + pad * 2 + (24 if notes else 0)
            built.append((l_lines, r_lines, h))
        total = sum(b[2] for b in built)
        if y + total <= bottom:
            break
    free = bottom - y - total
    spread = min(40, free / max(1, len(built))) if free > 0 else 0
    angles = (-1.2, 1.0, -0.9, 1.2)
    for i, (l_lines, r_lines, h) in enumerate(built):
        if i:
            draw.line([left * SCALE, (y - spread / 2) * SCALE, (left + width) * SCALE, (y - spread / 2) * SCALE], fill=(*p.text, 38), width=1 * SCALE)
        ty = y + pad
        end = draw_lines(draw, left, ty, l_lines, lf, p.muted, size, 1.3)
        for k, line in enumerate(l_lines):  # the common way, struck out
            lw = draw.textlength(line, font=lf) / SCALE
            sy = ty + k * size * 1.3 + size * 0.68
            stroke(draw, [(left - 4, sy + 1), (left + lw + 6, sy - 2)], p.accent, 3.6, p.rng, wobble=0.7)
        arrow(draw, left + col_w + 22, left + col_w + mid - 22, y + h / 2, p.accent, p.rng)
        rx = left + col_w + mid
        if not notes:
            draw_lines(draw, rx, ty, r_lines, rf, p.text, size, 1.3)
        else:
            nw, nh = col_w + 14, h - 22

            def content(d, ox, oy, r_lines=r_lines, pad=pad):
                draw_lines(d, ox + 28, oy + pad - 4, r_lines, rf, INK, size, 1.3)

            paper(p.img, (nw, nh), (rx + nw / 2 - 6, y + h / 2), angles[i % 4], PASTELS[(i + look.seed) % len(PASTELS)], content, tape=True, tape_x=0.2)
        y += h + spread
    return finish(p, spec)


def render_flow(spec: dict, brand: Brand) -> Image.Image:
    """Steps in order joined by a hand-drawn path. Variant 0: a winding path with numbered circles, text alternating
    sides. Variant 1: boxed steps stacked in a ladder with a drawn arrow between each."""
    p = start(spec, brand)
    draw, look = p.draw, p.look
    steps = rows_of(spec, 5)
    left, width = 72, W - 144
    bottom, top_limit = H - 150, 200
    tface, tweight = look.face, (620 if look.face == "serif" else 750)
    n = len(steps)
    y0 = head(p, spec.get("headline", ""), top_limit, 300, range(72, 47, -2), 3) + 40
    avail = bottom - y0
    step_h = min(235, avail / n)
    tsize = 38 if step_h > 140 else 30
    bsize = 29 if step_h > 140 else 24
    tf, bf = font(tsize, tweight, tface), font(bsize, 450)
    if look.variant == 0:
        cx = left + 46
        x_text = left + 120
        text_w = width - 130
        centers = [y0 + step_h * i + step_h * 0.34 for i in range(n)]
        for i in range(n - 1):  # the path, wobbling a little between circles
            stroke(draw, [(cx + (6 if i % 2 else -6), centers[i] + 46), (cx + (-6 if i % 2 else 6), (centers[i] + centers[i + 1]) / 2), (cx, centers[i + 1] - 46)], p.accent, 4, p.rng, wobble=1.6)
        for i, s_ in enumerate(steps):
            cy = centers[i]
            draw.ellipse([(cx - 40) * SCALE, (cy - 40) * SCALE, (cx + 40) * SCALE, (cy + 40) * SCALE], fill=p.accent)
            draw.text((cx * SCALE, (cy + 2) * SCALE), str(i + 1), font=font(46, 700, "hand"), fill=on_color(p.accent), anchor="mm")
            t_lines = wrap(draw, s_["title"], tf, text_w)[:2]
            ty = draw_lines(draw, x_text, cy - 30, t_lines, tf, p.text, tsize, 1.2)
            if s_.get("text"):
                draw_lines(draw, x_text, ty + 6, wrap(draw, s_["text"], bf, text_w)[:2], bf, p.muted, bsize, 1.35)
    else:
        box_h = step_h - 34
        for i, s_ in enumerate(steps):
            top = y0 + i * step_h
            fill = PASTELS[(i + look.seed) % len(PASTELS)]
            shift = 40 if i % 2 else 0

            def content(d, ox, oy, s_=s_, i=i):
                d.text(((ox + 34) * SCALE, (oy + box_h / 2) * SCALE), str(i + 1), font=font(70, 700, "hand"), fill=INK, anchor="lm")
                lines = wrap(d, s_["title"], tf, width - 260)[:2]
                body = wrap(d, s_["text"], bf, width - 260)[:2] if s_.get("text") else []
                block = len(lines) * tsize * 1.15 + (len(body) * bsize * 1.3 + 8 if body else 0)
                ty = draw_lines(d, ox + 100, oy + (box_h - block) / 2, lines, tf, INK, tsize, 1.15)
                if body:
                    draw_lines(d, ox + 100, ty + 8, body, bf, INK_SOFT, bsize, 1.3)

            paper(p.img, (width - 100, box_h), (left + shift + (width - 100) / 2, top + box_h / 2), (-0.8, 0.9)[i % 2], fill, content, tape=False)
            if i < n - 1:
                ax = left + width / 2 + (shift if i % 2 == 0 else 0)
                stroke(draw, [(ax, top + box_h + 4), (ax + 3, top + step_h - 2)], p.accent, 4, p.rng, wobble=0.6)
                stroke(draw, [(ax - 11, top + step_h - 16), (ax + 3, top + step_h - 2), (ax + 14, top + step_h - 16)], p.accent, 4, p.rng, wobble=0.4)
    return finish(p, spec)


def render_grid(spec: dict, brand: Brand) -> Image.Image:
    """Parallel ideas as cards. Variant 0: tilted notes in a 2-column grid. Variant 1: ruled columns with large numerals."""
    p = start(spec, brand)
    draw, look = p.draw, p.look
    cards = rows_of(spec, 4)
    left, width = 72, W - 144
    bottom, top_limit = H - 150, 200
    tface, tweight = look.face, (620 if look.face == "serif" else 750)
    y0 = head(p, spec.get("headline", ""), top_limit, 300, range(72, 47, -2), 3) + 44
    cols = 2 if len(cards) > 2 or look.variant == 0 else 1
    rows_n = math.ceil(len(cards) / cols)
    gap = 34
    cw = (width - gap * (cols - 1)) / cols
    ch = min(430, (bottom - y0 - gap * (rows_n - 1)) / rows_n)
    tsize, bsize = (40, 30) if ch > 250 else (32, 25)
    tf, bf = font(tsize, tweight, tface), font(bsize, 450)
    for i, c_ in enumerate(cards):
        col, row = i % cols, i // cols
        x, y = left + col * (cw + gap), y0 + row * (ch + gap)
        t_lines = wrap(draw, c_["title"], tf, cw - 70)[:3]
        b_lines = wrap(draw, c_.get("text", ""), bf, cw - 70)[:4] if c_.get("text") else []
        if look.variant == 0:
            def content(d, ox, oy, t_lines=t_lines, b_lines=b_lines):
                ty = draw_lines(d, ox + 34, oy + 34, t_lines, tf, INK, tsize, 1.15)
                if b_lines:
                    draw_lines(d, ox + 34, ty + 10, b_lines, bf, INK_SOFT, bsize, 1.35)

            paper(p.img, (cw - 12, ch - 12), (x + cw / 2, y + ch / 2), (-1.4, 1.1, 0.9, -1.0)[i % 4], PASTELS[(i + look.seed) % len(PASTELS)], content, tape=True, tape_x=0.25 + 0.5 * ((i * 3 % 5) / 5))
        else:
            draw.line([x * SCALE, y * SCALE, (x + cw) * SCALE, y * SCALE], fill=p.text, width=3 * SCALE)
            draw.text((x * SCALE, (y + 10) * SCALE), str(i + 1), font=font(96, 700, "hand"), fill=p.accent, anchor="la")
            ty = draw_lines(draw, x, y + 108, t_lines, tf, p.text, tsize, 1.15)
            if b_lines:
                draw_lines(draw, x, ty + 8, b_lines, bf, p.muted, bsize, 1.35)
    return finish(p, spec)


def print_wear(img: Image.Image) -> Image.Image:
    """What a flat digital fill never has: paper that is a touch uneven in tone, and corners that fall off a little, like a photographed print."""
    blotch = Image.effect_noise((9, 11), 3).resize((W, H), Image.BICUBIC).convert("RGB")
    img = ImageChops.add(img, blotch, 1.0, -128)  # +-a few levels of slow, soft variation
    edge = Image.radial_gradient("L").resize((W, H), Image.BICUBIC)  # 0 in the centre, 255 at the corners
    shade = edge.point(lambda v: round(v * 0.05))
    return ImageChops.subtract(img, Image.merge("RGB", (shade, shade, shade)))


def render_poster(spec: dict, brand: Brand) -> bytes:
    """PNG bytes of the poster described by `spec`."""
    template = spec.get("template") if spec.get("template") in TEMPLATES else "points"
    if brand.style == "personal":
        primary, accent = personal_theme(spec)
        brand = replace(brand, primary=primary, accent=accent)
    img = {
        "points": render_points, "stat": render_stat, "statement": render_statement, "compare": render_compare, "checklist": render_checklist,
        "flow": render_flow, "grid": render_grid,
    }[template](spec, brand)
    img = img.resize((W, H), Image.LANCZOS)
    img = print_wear(img)
    grain = Image.effect_noise((W, H), 9).convert("RGB")  # paper grain, drawn before the logo so the logo stays exactly as uploaded
    img = ImageChops.add(img, grain, 1.0, -128)
    paste_logo(img, brand)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
