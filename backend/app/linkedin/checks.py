"""Rules a written post must pass before anyone sees it: no clichés, no invented numbers, no invented stories.

Plain functions with no I/O, so every rule is tested on its own. A failed check returns the reason, which is given
back to the writer so it can fix exactly that.
"""

import re

from app.linkedin.poster import TEMPLATES, Brand
from app.linkedin.schemas import PosterSpec
from app.models import utcnow

BANNED = (
    "in today's fast-paced", "fast-paced world", "in the ever-evolving", "ever-evolving", "game-changer", "game changer", "unlock the",
    "delve", "revolutionize", "revolutionise", "seamless", "cutting-edge", "cutting edge", "let's dive", "dive into", "it's no secret",
    "in this post", "i'm thrilled", "i am thrilled", "excited to announce", "buckle up", "at the end of the day", "navigate the",
    "landscape", "tapestry", "testament to", "leverage", "synergy", "supercharge", "elevate your", "take your business to the next level",
    "here's the thing", "let that sink in", "read that again", "agree?", "thoughts?", "hot take", "no longer just", "not just about",
    "more than just", "maintenance nightmare", "100% accuracy", "100% data accuracy", "guarantee",
)
# Things that happened to the writer. Only allowed when the owner's own facts say so.
INVENTED_EXPERIENCE = (
    "a client of mine", "one of my clients", "one of our clients", "my client ", "our client ", "a client told me", "a client asked me",
    "a client recently", "we recently", "i recently", "last week i", "last month i", "last year i", "last week we", "last month we",
    "we helped", "i helped", "we delivered", "i delivered", "we built for", "i built for", "case study", "customer told us", "testimonial",
    "we saved", "i saved", "increased their revenue", "doubled their", "tripled their",
)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐⬆✅]")
PLACEHOLDER = re.compile(r"\[[^\]\n]{1,40}\]|\{\{?[^}\n]{1,30}\}?\}")
MENTION = re.compile(r"@([A-Za-z][\w]*)")
HASHTAG = re.compile(r"^#[A-Za-z][A-Za-z0-9]{1,30}$")
NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
EXPERIENCE_CLAIM = re.compile(r"(?<![\d,.$])(\d[\d,]*)\+?\s+(?:years?|clients?|customers?|projects?|businesses|companies|apps?)\b", re.I)


def clean_post(text: str) -> str:
    """Strip what makes a post look machine-written: markdown, dashes, curly quotes and stray blank lines."""
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text, flags=re.S)
    text = re.sub(r"(?m)^[ \t]{0,3}#{1,6}[ \t]+", "", text)  # markdown headings; a hashtag has no space after #
    text = text.replace("*", "")
    text = re.sub(r"\s*[—–]\s*", ", ", text)  # em and en dashes
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"(?m)^[ \t]*[•▪●◦][ \t]+", "- ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def post_problem(text: str, allowed_mentions: list[str]) -> str | None:
    if len(text) < 450:
        return f"too short: {len(text)} characters, write at least 600"
    if len(text) > 1900:
        return f"too long: {len(text)} characters, stay under 1700"
    first = text.split("\n", 1)[0]
    if len(first) > 120:
        return f"the first line is {len(first)} characters; make the opening hook a short line under 100 characters, then a blank line"
    lowered = text.lower()
    for phrase in BANNED:
        if phrase in lowered:
            return f"it uses the cliche '{phrase}'; say the same thing in plain words"
    if len(EMOJI.findall(text)) > 2:
        return "it has more than two emojis; use none or one"
    found = PLACEHOLDER.search(text)
    if found:
        return f"it contains a placeholder: {found.group(0)}"
    for m in MENTION.findall(text):
        if m not in allowed_mentions:
            return f"it tags @{m}, which cannot be tagged; remove it"
    if re.search(r"(?m)^\s*(?:Hook|CTA|Post|Hashtags?)\s*:", text):
        return "it contains a label such as 'Hook:'; write only the post"
    return None


def number_key(token: str) -> str:
    return token.replace(",", "").lstrip("$").rstrip("%").rstrip(".")


def known_numbers(*sources: str) -> set[str]:
    """Every number in the facts the writer was given: the only numbers a post may state."""
    return {number_key(m.group(0)) for text in sources for m in NUMBER.finditer(text)}


def fact_problem(text: str, facts_text: str) -> str | None:
    """Catches the two ways a post turns false: made-up statistics and made-up things that happened."""
    lowered = text.lower()
    facts = facts_text.lower()
    for phrase in INVENTED_EXPERIENCE:
        if phrase in lowered and phrase not in facts:
            return f"it says '{phrase.strip()}', an event that is not in <about>; write it as general advice or as a plainly hypothetical example ('Say a clinic wants...')"
    allowed = known_numbers(facts_text)
    this_year = str(utcnow().year)
    for m in NUMBER.finditer(text):
        token = m.group(0)
        value = number_key(token)
        if not value or value in allowed or value in (this_year, str(int(this_year) - 1)):
            continue
        # A percentage, an amount of money or a big count is a claim about the world and needs a source in the given data.
        try:
            big = float(value) >= 100
        except ValueError:
            continue
        if token.endswith("%") or token.startswith("$") or big:
            return f"it states the number {token}, which is not in <research>, <website> or <about>; remove it or use only the numbers you were given"
    for m in EXPERIENCE_CLAIM.finditer(text):
        if m.group(0).lower() not in facts and number_key(m.group(1)) not in allowed:
            return f"it claims '{m.group(0)}', which is not in <about>"
    return None


def poster_problem(raw: dict, facts_text: str) -> str | None:
    """The poster is held to the same rules as the post: a number on it must come from the given data."""
    parts = [str(raw.get("headline", "")), str(raw.get("stat", "")), str(raw.get("stat_label", "")), str(raw.get("caption", ""))]
    for p in raw.get("points") or []:
        parts += [str(p.get("title", "")), str(p.get("text", ""))]
    found = fact_problem(" ".join(parts), facts_text)
    return f"the poster {found}" if found else None


def branding_problem(raw: dict, banned_words: list[str]) -> str | None:
    """A personal poster carries no company name, no website and no link: it is there to inform, not to advertise."""
    parts = [str(raw.get("kicker", "")), str(raw.get("headline", "")), str(raw.get("stat_label", "")), str(raw.get("caption", ""))]
    for p in raw.get("points") or []:
        parts += [str(p.get("title", "")), str(p.get("text", ""))]
    joined = " ".join(parts)
    lowered = joined.lower()
    for word in banned_words:
        if word.strip() and word.strip().lower() in lowered:
            return f"the poster mentions '{word.strip()}'; a poster for the personal profile never names the company"
    if re.search(r"https?://|www\.|[a-z0-9-]+\.(?:com|io|dev|co|net|org|ai)", lowered):
        return "the poster contains a website or link; a poster for the personal profile has none"
    return None


def poster_from(raw: dict, mode: str, post: str, brand: Brand) -> dict | None:
    """The poster spec the writer asked for, cleaned up; None when there should be no poster."""
    if mode == "never":
        return None
    if not (raw or {}).get("needed") and mode != "always":
        return None
    template = raw.get("template") if raw.get("template") in TEMPLATES else "points"
    # The poster numbers the points itself, so a "1." the writer put in front would show twice.
    points = [
        {"title": re.sub(r"^\s*\d+[.):]\s*", "", " ".join(str(p.get("title", "")).split()))[:70], "text": " ".join(str(p.get("text", "")).split())[:140]}
        for p in raw.get("points") or []
    ]
    points = [p for p in points if p["title"]][:5]
    spec = {
        "template": template,
        "kicker": " ".join(str(raw.get("kicker", "")).split())[:26],
        "headline": " ".join(str(raw.get("headline", "")).split())[:110],
        "points": points,
        "stat": " ".join(str(raw.get("stat", "")).split())[:14],
        "stat_label": " ".join(str(raw.get("stat_label", "")).split())[:110],
        "caption": " ".join(str(raw.get("caption", "")).split())[:200],
        "footer": "",
    }
    if template in ("points", "compare", "checklist") and (len(points) < 2 or not spec["headline"]):
        template = spec["template"] = "statement"
    if template == "stat" and not (spec["stat"] and spec["stat_label"]):
        template = spec["template"] = "statement"
    if template == "statement" and not spec["headline"]:
        if mode != "always":
            return None
        spec["headline"] = post.split("\n", 1)[0][:110]
    return PosterSpec(**spec).model_dump()
