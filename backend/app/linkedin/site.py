"""What the company website says about the company, read from the site itself.

The text is kept for a week. Posts for the company page may state as fact anything that is on it, and nothing else
about the company: this is where its services, process and technologies come from.
"""

import logging
import re
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.linkedin.models import LinkedInCache
from app.models import utcnow

logger = logging.getLogger("easybid")

KEY = "site"
MAX_AGE = timedelta(days=7)
MAX_CHARS = 7000
PAGES = ("", "about", "services")


class _Text(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "head"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("br", "p", "div", "li", "h1", "h2", "h3", "h4", "section", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag in ("p", "div", "li", "h1", "h2", "h3", "h4", "section"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip and data.strip():
            self.parts.append(f" {data.strip()} ")


def page_text(html: str) -> str:
    parser = _Text()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return "\n".join(line.strip() for line in text.split("\n") if len(line.strip()) > 1).strip()


async def fetch_site(url: str) -> str:
    """The readable text of the home page and its about and services pages."""
    base = url.rstrip("/") + "/"
    seen: set[str] = set()
    chunks: list[str] = []
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (compatible; codevryn-content-bot)"}) as http:
        for page in PAGES:
            target = urljoin(base, page)
            if urlparse(target).netloc != urlparse(base).netloc:
                continue
            try:
                res = await http.get(target)
            except httpx.HTTPError as e:
                logger.info("LinkedIn: could not read %s: %r", target, e)
                continue
            if res.status_code != 200 or "html" not in res.headers.get("content-type", ""):
                continue
            text = page_text(res.text)
            if text and text[:200] not in seen:
                seen.add(text[:200])
                chunks.append(f"[{urlparse(target).path or '/'}]\n{text}")
    return "\n\n".join(chunks)[:MAX_CHARS]


async def get_site(session: AsyncSession, url: str, force: bool = False) -> dict:
    """{'url', 'text', 'fetched_at'}; the saved copy unless it is a week old, the address changed or `force`."""
    if not url:
        return {"url": "", "text": "", "fetched_at": None}
    row = await session.get(LinkedInCache, KEY)
    fresh = row and row.data.get("url") == url and row.data.get("text") and utcnow() - row.fetched_at < MAX_AGE
    if fresh and not force:
        return {**row.data, "fetched_at": row.fetched_at.isoformat()}
    text = await fetch_site(url)
    if not text:
        # Keep the old copy rather than lose what we knew.
        return {**row.data, "fetched_at": row.fetched_at.isoformat()} if row and row.data.get("url") == url else {"url": url, "text": "", "fetched_at": None}
    data = {"url": url, "text": text}
    if row is None:
        row = LinkedInCache(key=KEY)
        session.add(row)
    row.data, row.fetched_at = data, utcnow()
    await session.flush()
    return {**data, "fetched_at": row.fetched_at.isoformat()}
