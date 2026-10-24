"""Fill an email template for one recipient.

Syntax:
  {{name}}              the recipient's value; {{first_name}}, {{company}}, {{email}}, {{domain}} are always known,
                        every other column of the imported sheet is available under its own name
  {{first_name|there}}  the text after | is used when the value is empty
  {Hi|Hello|Hey}        one of the options, chosen by the recipient's seed so a preview matches what is sent
"""

import random
import re
from dataclasses import dataclass, field

VARIABLE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_ ]{0,40}?)\s*(?:\|([^{}]*))?\}\}")
# Single braces with a bar inside; the lookarounds leave {{ }} alone.
SPIN = re.compile(r"(?<!\{)\{([^{}]*\|[^{}]*)\}(?!\})")

BUILTIN = ("name", "first_name", "last_name", "company", "email", "domain")


@dataclass
class Rendered:
    text: str
    missing: list[str] = field(default_factory=list)  # variables that were empty and had no fallback


def key(name: str) -> str:
    """'First Name' and 'first-name' and 'FIRST_NAME' are the same column."""
    return re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")


def context(email: str, name: str, company: str, fields: dict) -> dict[str, str]:
    """Every variable a template can use for this recipient."""
    parts = name.split()
    ctx = {key(k): str(v).strip() for k, v in fields.items() if v is not None}
    ctx.update(
        name=name.strip(),
        first_name=parts[0] if parts else "",
        last_name=" ".join(parts[1:]),
        company=company.strip(),
        email=email,
        domain=email.rsplit("@", 1)[-1] if "@" in email else "",
    )
    return ctx


def variables_in(template: str) -> list[str]:
    """Variable names used, in order, without repeats."""
    seen: list[str] = []
    for match in VARIABLE.finditer(template):
        name = key(match.group(1))
        if name not in seen:
            seen.append(name)
    return seen


def unknown_variables(template: str, known: set[str]) -> list[str]:
    """Variables that are neither built in nor in `known` and have no fallback; they would always come out empty."""
    unknown: list[str] = []
    for match in VARIABLE.finditer(template):
        name = key(match.group(1))
        if name not in BUILTIN and name not in known and match.group(2) is None and name not in unknown:
            unknown.append(name)
    return unknown


def render(template: str, ctx: dict[str, str], seed: int | str = 0) -> Rendered:
    rng = random.Random(str(seed))
    missing: list[str] = []

    def spin(match: re.Match) -> str:
        return rng.choice(match.group(1).split("|")).strip()

    def fill(match: re.Match) -> str:
        name = key(match.group(1))
        value = ctx.get(name, "")
        if value:
            return value
        if match.group(2) is not None:
            return match.group(2).strip()
        if name not in missing:
            missing.append(name)
        return ""

    # Options first, so a value from the sheet that happens to contain braces is never read as an option list.
    return Rendered(text=VARIABLE.sub(fill, SPIN.sub(spin, template)), missing=missing)
