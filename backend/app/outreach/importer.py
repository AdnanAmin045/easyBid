"""Read a recipient list: a pasted column of addresses, free text, or a CSV/TSV sheet with a header row.

A header row maps columns to the recipient: email (required), name, company, subject and body. Every other column
is kept and becomes a template variable. When a row has its own subject and body, those are sent as written.
"""

import csv
import io
import re
from dataclasses import dataclass, field

from email_validator import EmailNotValidError, validate_email

from app.jobs.extract import find_emails
from app.outreach.render import key

ALIASES = {
    "email": {"email", "e_mail", "email_address", "mail", "address", "recipient", "to"},
    "name": {"name", "full_name", "fullname", "contact", "contact_name", "person"},
    "first_name": {"first_name", "firstname", "first", "given_name"},
    "last_name": {"last_name", "lastname", "last", "surname", "family_name"},
    "company": {"company", "company_name", "organization", "organisation", "employer", "business"},
    "subject": {"subject", "email_subject"},
    "body": {"body", "email_body", "message", "content", "mail_body"},
}
DELIMITERS = (",", "\t", ";", "|")
NAMED_ADDRESS = re.compile(r'^\s*"?([^"<>]*?)"?\s*<\s*([^<>\s]+@[^<>\s]+)\s*>\s*$')


@dataclass
class Row:
    email: str
    name: str = ""
    company: str = ""
    subject: str = ""
    body: str = ""
    fields: dict = field(default_factory=dict)
    line: int = 0


@dataclass
class Rejected:
    line: int
    value: str
    reason: str


@dataclass
class Sheet:
    rows: list[Row] = field(default_factory=list)
    rejected: list[Rejected] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)  # extra columns found, usable as {{variables}}
    has_header: bool = False


def clean_address(value: str) -> tuple[str, str] | None:
    """(email, name) from 'a@b.com' or 'Ann <a@b.com>', or None when it is not a valid address."""
    name = ""
    named = NAMED_ADDRESS.match(value)
    if named:
        name, value = named.group(1).strip(), named.group(2)
    try:
        email = validate_email(value.strip().strip("<>;,"), check_deliverability=False).normalized.lower()
    except EmailNotValidError:
        return None
    return email, name


def _header_map(cells: list[str]) -> dict[int, str] | None:
    """Column index -> role (or the column's own key) when this row is a header with an email column."""
    roles: dict[int, str] = {}
    for i, cell in enumerate(cells):
        name = key(cell)
        if not name:
            continue
        role = next((r for r, names in ALIASES.items() if name in names), None)
        roles[i] = role or name
    return roles if "email" in roles.values() else None


def _header(text: str) -> tuple[str, dict[int, str]] | None:
    first = next((line for line in text.splitlines() if line.strip()), "")
    for delimiter in DELIMITERS:
        mapping = _header_map(next(csv.reader([first], delimiter=delimiter), []))
        if mapping:
            return delimiter, mapping
    return None


def _from_sheet(text: str, delimiter: str, mapping: dict[int, str]) -> Sheet:
    sheet = Sheet(has_header=True)
    seen: set[str] = set()
    extra = [role for role in mapping.values() if role not in ALIASES]
    sheet.columns = list(dict.fromkeys(extra))
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    next(reader, None)  # the header
    for cells in reader:
        if not any(c.strip() for c in cells):
            continue
        values: dict[str, str] = {}
        for i, role in mapping.items():
            values.setdefault(role, cells[i].strip() if i < len(cells) else "")
        line = reader.line_num
        raw = values.get("email", "")
        address = clean_address(raw) if raw else None
        if not address:
            sheet.rejected.append(Rejected(line, raw, "Not a valid email address" if raw else "No email in this row"))
            continue
        email, embedded_name = address
        if email in seen:
            sheet.rejected.append(Rejected(line, email, "Duplicate in this list"))
            continue
        seen.add(email)
        name = values.get("name") or " ".join(p for p in (values.get("first_name"), values.get("last_name")) if p) or embedded_name
        sheet.rows.append(
            Row(
                email=email,
                name=name[:200],
                company=values.get("company", "")[:200],
                subject=" ".join(values.get("subject", "").split())[:300],
                body=values.get("body", "").replace("\r\n", "\n").strip(),
                fields={c: values[c] for c in sheet.columns if values.get(c)},
                line=line,
            )
        )
    return sheet


def _from_free_text(text: str) -> Sheet:
    sheet = Sheet()
    seen: set[str] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        named = NAMED_ADDRESS.match(line)
        candidates = [line] if named else find_emails(line)
        found = [address for address in map(clean_address, candidates) if address]
        if not found:
            sheet.rejected.append(Rejected(number, line.strip()[:200], "No email address found"))
            continue
        for email, name in found:
            if email in seen:
                sheet.rejected.append(Rejected(number, email, "Duplicate in this list"))
                continue
            seen.add(email)
            sheet.rows.append(Row(email=email, name=name[:200], line=number))
    return sheet


def parse(text: str) -> Sheet:
    text = text.lstrip("﻿")
    header = _header(text)
    return _from_sheet(text, *header) if header else _from_free_text(text)
