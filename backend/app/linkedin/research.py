"""What is happening in the field this week, looked up on the web every day.

Two kinds of source, both free:
  Google Search through Gemini: the model searches the web itself and reports what it found, with the pages it used.
  News and developer feeds: Google News, Hacker News and dev.to, read directly. Always fetched, and the only source
  when the search tool is out of quota.

The result is kept for the day and shared by the personal and company posts. Nothing here comes from Freelancer.
"""

import asyncio
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.linkedin.models import LinkedInCache
from app.linkedin.schemas import LinkedInSettings
from app.models import utcnow
from app.services.llm import LLM, LLMError

logger = logging.getLogger("easybid")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; codevryn-content-bot)"}
MAX_FIELDS = 4  # fields looked up in the feeds each day, to stay polite and fast


@dataclass
class Research:
    day: str
    digest: str  # what the writer reads
    sources: list[dict] = field(default_factory=list)  # [{'title', 'url'}] shown next to the post
    via: str = ""  # "search+feeds" | "feeds"

    def as_dict(self) -> dict:
        return {"day": self.day, "digest": self.digest, "sources": self.sources, "via": self.via}


async def _get(http: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        res = await http.get(url)
        res.raise_for_status()
        return res
    except httpx.HTTPError as e:
        logger.info("LinkedIn research: %s unavailable: %r", url.split("/")[2], e)
        return None


def _clean(text: str | None) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", text or "").split())


async def google_news(http: httpx.AsyncClient, topic: str) -> list[dict]:
    res = await _get(http, f"https://news.google.com/rss/search?q={quote(topic)}+when:7d&hl=en-US&gl=US&ceid=US:en")
    if res is None:
        return []
    try:
        root = ET.fromstring(res.text)
    except ET.ParseError:
        return []
    items = []
    for item in root.iterfind("./channel/item"):
        title = _clean(item.findtext("title"))
        if title:
            items.append({"title": title, "url": item.findtext("link") or "", "source": _clean(item.findtext("source")), "topic": topic})
        if len(items) == 4:
            break
    return items


async def hacker_news(http: httpx.AsyncClient, topic: str) -> list[dict]:
    since = int((utcnow() - timedelta(days=7)).timestamp())
    res = await _get(http, f"https://hn.algolia.com/api/v1/search?query={quote(topic)}&tags=story&numericFilters=created_at_i>{since},points>40&hitsPerPage=4")
    if res is None:
        return []
    return [
        {"title": h["title"], "url": f"https://news.ycombinator.com/item?id={h['objectID']}", "source": f"Hacker News, {h.get('points', 0)} points", "topic": topic}
        for h in res.json().get("hits", [])
        if h.get("title")
    ]


async def devto(http: httpx.AsyncClient) -> list[dict]:
    res = await _get(http, "https://dev.to/api/articles?top=7&per_page=10")
    if res is None:
        return []
    # Only articles many developers reacted to; the rest of dev.to is mostly personal posts.
    return [
        {"title": a["title"], "url": a.get("url", ""), "source": "dev.to", "topic": ""}
        for a in res.json()
        if a.get("title") and a.get("public_reactions_count", 0) >= 40
    ][:6]


async def fetch_feeds(fields: list[str]) -> list[dict]:
    """Headlines from the last week about each field, from the free feeds."""
    topics = [f for f in fields if f.strip()][:MAX_FIELDS]
    async with httpx.AsyncClient(timeout=15, headers=HEADERS, follow_redirects=True) as http:
        batches = await asyncio.gather(*[google_news(http, t) for t in topics], *[hacker_news(http, t) for t in topics], devto(http))
    seen: set[str] = set()
    out = []
    for batch in batches:
        for item in batch:
            key = re.sub(r"\W+", "", item["title"].lower())[:60]
            if key not in seen:
                seen.add(key)
                out.append(item)
    return out


def search_prompt(fields: list[str], day: date) -> tuple[str, str]:
    system = (
        "You are a research analyst for a software engineering studio's LinkedIn. Use Google Search. Report only what you actually find "
        "in pages you searched: never fill gaps from memory, and never invent a number, date, product or quote."
    )
    user = (
        f"Today is {day.isoformat()}. Search the web for what happened in the last 7 days (older only if it is still the main story) in these fields:\n"
        + "\n".join(f"- {f}" for f in fields)
        + "\n\nGive 8 to 10 items that a founder or engineering lead would care about: releases, price or policy changes, "
        "security incidents, notable launches, widely shared engineering write-ups, shifts in how teams build. Prefer facts that can change a "
        "decision over opinions.\n\nOne item per line in exactly this form:\n"
        "HEADLINE | what happened and why it matters, in one or two sentences with the specific facts you found | source name\n\n"
        "No introduction and no closing remarks."
    )
    return system, user


def parse_search(text: str) -> list[str]:
    lines = [ln.strip(" -*•\t") for ln in text.splitlines()]
    return [ln for ln in lines if ln.count("|") >= 2][:12]


def digest_of(found: list[str], feeds: list[dict]) -> str:
    parts = []
    if found:
        parts.append("FOUND BY WEB SEARCH (headline | what happened and why it matters | source):\n" + "\n".join(f"- {ln}" for ln in found))
    if feeds:
        parts.append(
            "HEADLINES FROM NEWS AND DEVELOPER FEEDS THIS WEEK (headline only, details unknown):\n"
            + "\n".join(f"- {i['title']} ({i['source'] or 'news'})" for i in feeds[:24])
        )
    return "\n\n".join(parts)


async def gather(llm: LLM, s: LinkedInSettings, day: date) -> Research:
    feeds_task = asyncio.create_task(fetch_feeds(s.fields))
    found: list[str] = []
    sources: list[dict] = []
    try:
        system, user = search_prompt(s.fields, day)
        text, pages = await llm.search(model=s.model, system=system, user=user)
        found = parse_search(text) or [ln for ln in text.splitlines() if ln.strip()][:12]
        sources = [p for p in pages if p.get("url")][:12]
    except LLMError as e:
        logger.info("LinkedIn research: web search unavailable, using the feeds only: %s", e)
    feeds = await feeds_task
    seen = {p["url"] for p in sources}
    sources += [{"title": i["title"], "url": i["url"]} for i in feeds if i["url"] and i["url"] not in seen][:10]
    return Research(day=day.isoformat(), digest=digest_of(found, feeds), sources=sources, via="search+feeds" if found else "feeds")


async def get_research(llm: LLM, session: AsyncSession, s: LinkedInSettings, day: date, force: bool = False) -> Research:
    """Today's research: the saved copy, unless there is none, the fields changed or `force`."""
    key = f"research:{day.isoformat()}"
    row = await session.get(LinkedInCache, key)
    if row and not force and row.data.get("digest") and row.data.get("fields") == s.fields:
        d = row.data
        return Research(day=d["day"], digest=d["digest"], sources=d.get("sources", []), via=d.get("via", ""))
    research = await gather(llm, s, day)
    if not research.digest:
        if row and row.data.get("digest"):  # nothing new could be fetched; yesterday's lookup beats none
            d = row.data
            return Research(day=d["day"], digest=d["digest"], sources=d.get("sources", []), via=d.get("via", ""))
        raise LLMError("Could not look up anything about the field: the search and the news feeds are all unreachable", transient=True)
    if row is None:
        row = LinkedInCache(key=key)
        session.add(row)
    row.data, row.fetched_at = {**research.as_dict(), "fields": s.fields}, datetime.now(timezone.utc)
    await session.flush()
    return research
