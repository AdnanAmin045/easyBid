from datetime import date, datetime, time
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

Target = Literal["personal", "company"]
HEX = r"^#[0-9a-fA-F]{6}$"


def _clock(value: str) -> str:
    try:
        h, m = value.split(":")
        time(int(h), int(m))
    except (ValueError, TypeError):
        raise ValueError("Use the 24-hour format HH:MM, for example 19:30") from None
    return f"{int(h):02d}:{int(m):02d}"


class TargetSettings(BaseModel):
    """How one of the two profiles posts."""

    enabled: bool = False
    # On: approved as soon as it is written and posted at post_time. Off: waits in the dashboard for a tap.
    auto_approve: bool = False
    post_time: str = "19:00"
    # Weekdays to post on, Monday = 0
    days: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4, 5, 6], max_length=7)
    # Who writes: shapes the voice. Plain sentences, in the writer's own words.
    voice: str = Field("", max_length=1500)
    # Facts the posts may claim (services, years, tools, results). Nothing outside this and the market data is stated as fact.
    about: str = Field("", max_length=3000)
    audience: str = Field("", max_length=500)
    # Posted as the first comment right after the post, for example "Book a free 20-minute call: https://..."
    first_comment: str = Field("", max_length=1000)
    # auto: a poster when the topic suits one; always; never
    poster: Literal["auto", "always", "never"] = "auto"
    # Topics to avoid or to push; free text read by the writer.
    notes: str = Field("", max_length=1500)

    @field_validator("post_time")
    @classmethod
    def _post_time(cls, v: str) -> str:
        return _clock(v)

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d < 0 or d > 6 for d in v):
            raise ValueError("Days are 0 (Monday) to 6 (Sunday)")
        return sorted(set(v))


def personal_defaults() -> TargetSettings:
    """Recommended settings for the personal profile: posts at 9 am US Eastern (7 pm Pakistan), a week of different post types."""
    return TargetSettings(
        enabled=True,
        auto_approve=False,
        post_time="19:00",
        voice="A working full-stack developer who builds SaaS products, web apps and AI features for clients, and writes the way he talks to a colleague. "
        "First person ('I'), practical and specific, a little opinionated, honest about trade-offs and mistakes. Teaches before selling; never salesy, never hype.",
        audience="Founders, CTOs, product owners and engineering leads at startups and small or mid-sized companies who are building, or about to build, "
        "a web product, a SaaS app or an AI feature. Also developers who want practical, honest engineering advice.",
        notes="Stay on web and software engineering, AI features, performance and delivery. No politics, religion, layoff gossip or attacks on named people "
        "or companies. Never reveal a client's confidential details. Prefer concrete engineering detail over motivational talk. End with a real question "
        "that a founder or engineer can answer in one line.",
        poster="auto",
    )


def company_defaults() -> TargetSettings:
    """Recommended settings for the company page: posts at 10:30 am US Eastern (8:30 pm Pakistan), with a booking link as the first comment."""
    return TargetSettings(
        enabled=True,
        auto_approve=False,
        post_time="20:30",
        voice="Codevryn, a software engineering partner. We write as 'we': calm, clear and specific, a senior team explaining how good work gets done. "
        "No hype, no buzzwords, no promises of results. Transparent and predictable, in the spirit of the website: software that holds up.",
        audience="Founders, product owners and operations leaders at startups and growing businesses who need a reliable development partner for a web "
        "platform, a backend or API, a cloud setup, performance work or an AI feature.",
        first_comment="Planning a build or need a second opinion? Tell us about it: https://codevryn.com/contact",
        notes="Cover only the services and technologies on the website. No invented client names, results or prices. No politics or gossip. Never criticise "
        "competitors by name. End with a question or an open invitation to talk, not a hard sell.",
        poster="auto",
    )


class Pillar(BaseModel):
    """What one weekday's post is about."""

    name: str = Field(max_length=40)
    instruction: str = Field(max_length=800)


class PromptSettings(BaseModel):
    """The instructions the planner and the writer follow. Blank (or no rows) means the built-in recommended text.

    The truth rules are not here: they are always added and enforced in code.
    """

    writer_style: str = Field("", max_length=6000)
    planner_guidance: str = Field("", max_length=4000)
    poster_guidance: str = Field("", max_length=4000)
    # Seven rows, Monday first, or none for the recommended week.
    personal_pillars: list[Pillar] = Field(default_factory=list, max_length=7)
    company_pillars: list[Pillar] = Field(default_factory=list, max_length=7)

    @field_validator("personal_pillars", "company_pillars")
    @classmethod
    def _seven(cls, v: list[Pillar]) -> list[Pillar]:
        if v and len(v) != 7:
            raise ValueError("A week has seven rows, Monday to Sunday")
        return v


class LinkedInSettings(BaseModel):
    """Stored as the JSON document of the linkedin_config row."""

    timezone: str = "Asia/Karachi"
    # When the day's draft is written, local time. Leave a few hours before the posting time to review it.
    generate_time: str = "12:00"
    model: str = "gemini-3.5-flash"
    # Tried in order when the model above is out of free quota. A model whose API key is not set is skipped,
    # so adding GROQ_API_KEY (free) is all it takes to make "groq/..." work.
    fallback_models: list[str] = Field(default_factory=lambda: ["groq/llama-3.3-70b-versatile"], max_length=4)
    brand_name: str = Field("Codevryn", max_length=60)
    website: str = Field("", max_length=120)
    # Read for what the company does and offers: company posts may state anything that is on it.
    website_url: str = Field("https://codevryn.com", max_length=200)
    # The fields to watch. Each day the web is searched for what happened in them, and the posts are about that.
    fields: list[str] = Field(
        default_factory=lambda: [
            "AI agents and LLM applications in production",
            "Next.js and React web development",
            "FastAPI, Python and Node.js backend engineering",
            "Cloud, DevOps and web performance",
        ],
        max_length=6,
    )
    brand_primary: str = Field("#F5F8FC", pattern=HEX)
    brand_accent: str = Field("#1E3A5F", pattern=HEX)
    # Posters of the personal profile look different from the company's: no logo, no website, just the person.
    # Blank name: the name of the connected LinkedIn account.
    personal_name: str = Field("", max_length=80)
    personal_title: str = Field("Full-stack developer", max_length=60)
    personal_primary: str = Field("#0D1117", pattern=HEX)
    personal_accent: str = Field("#F59E0B", pattern=HEX)
    # Names the writer may tag with @Name, and the LinkedIn URN each one stands for. LinkedIn only turns a name
    # into a link when it matches the page's name exactly; people cannot be tagged through the API.
    mentions: dict[str, str] = Field(default_factory=dict)
    # The numeric id of the company page, from linkedin.com/company/<id>/admin/. Needed for the company page.
    company_page_id: str = Field("", max_length=20, pattern=r"^\d*$")
    # Write the day's drafts even when the page is not connected, so they can be copied by hand.
    draft_without_connection: bool = True
    prompts: PromptSettings = Field(default_factory=PromptSettings)
    personal: TargetSettings = Field(default_factory=personal_defaults)
    company: TargetSettings = Field(default_factory=company_defaults)

    @field_validator("fields")
    @classmethod
    def _fields(cls, v: list[str]) -> list[str]:
        cleaned = [" ".join(f.split())[:120] for f in v if f.strip()]
        if not cleaned:
            raise ValueError("Add at least one field to watch")
        return cleaned

    @field_validator("generate_time")
    @classmethod
    def _generate_time(cls, v: str) -> str:
        return _clock(v)

    @field_validator("timezone")
    @classmethod
    def _timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown time zone: {v}. Use a name such as Asia/Karachi or America/New_York") from None
        return v

    @field_validator("mentions")
    @classmethod
    def _mentions(cls, v: dict[str, str]) -> dict[str, str]:
        for name, urn in v.items():
            if not name.strip() or not urn.startswith(("urn:li:organization:", "urn:li:person:")):
                raise ValueError("Each mention is a name and a URN such as urn:li:organization:12345")
        return {k.strip(): u.strip() for k, u in v.items()}

    def for_target(self, target: str) -> TargetSettings:
        return self.personal if target == "personal" else self.company


class PosterPoint(BaseModel):
    title: str = Field("", max_length=70)
    text: str = Field("", max_length=140)


class PosterSpec(BaseModel):
    template: Literal["points", "stat", "statement", "compare", "checklist"] = "points"
    kicker: str = Field("", max_length=26)
    headline: str = Field("", max_length=110)
    points: list[PosterPoint] = Field(default_factory=list, max_length=5)
    stat: str = Field("", max_length=14)
    stat_label: str = Field("", max_length=110)
    caption: str = Field("", max_length=200)
    footer: str = Field("", max_length=40)


class PostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target: str
    post_date: date
    slot: int
    pillar: str
    topic: str
    text: str
    first_comment: str
    poster_spec: dict | None
    has_poster: bool
    alt_text: str
    signals: dict
    status: str
    scheduled_for: datetime | None
    posted_at: datetime | None
    linkedin_urn: str
    linkedin_url: str
    error: str
    created_at: datetime


class PostPatch(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=3000)
    first_comment: str | None = Field(None, max_length=1000)
    topic: str | None = Field(None, max_length=300)
    alt_text: str | None = Field(None, max_length=500)
    scheduled_for: datetime | None = None
    poster_spec: PosterSpec | None = None
    # Take the poster off the post
    remove_poster: bool = False


class GenerateIn(BaseModel):
    target: Target
    # Your own idea for the post. Blank: the writer picks the topic from this week's research.
    brief: str = Field("", max_length=1000)


class IdeasIn(BaseModel):
    target: Target
    count: int = Field(5, ge=1, le=8)


class Idea(BaseModel):
    topic: str
    angle: str = ""
    why_now: str = ""
    pillar: str = ""


class ApproveIn(BaseModel):
    scheduled_for: datetime | None = None


class AccountOut(BaseModel):
    target: str
    configured: bool  # the app credentials are on the server
    connected: bool
    name: str = ""
    author_urn: str = ""
    expires_at: datetime | None = None
    days_left: int | None = None
    problem: str = ""  # why posting from here cannot work yet


def _minutes(clock: str) -> int:
    h, m = clock.split(":")
    return int(h) * 60 + int(m)


def timing_problems(s: LinkedInSettings) -> list[dict]:
    """Mistakes in the posting times. An "error" blocks saving; a "warning" is only shown.

    The draft is written at generate_time and goes out at post_time, so post_time has to come after it, with time to read
    the draft in between. A post that goes out while the audience is asleep is wasted, so that is flagged too.
    """
    found: list[dict] = []
    tz = ZoneInfo(s.timezone)
    today = datetime.now(tz).date()
    generate = _minutes(s.generate_time)
    for target, label in (("personal", "Personal profile"), ("company", "Company page")):
        t = s.for_target(target)
        if not t.enabled:
            continue
        post = _minutes(t.post_time)
        if post <= generate:
            found.append({
                "level": "error", "target": target,
                "message": f"{label}: the post time {t.post_time} is not after the time the draft is written ({s.generate_time}). "
                f"Set the post time later, or write the draft earlier, so the draft is ready before it goes out.",
            })
            continue
        if post - generate < 60 and not t.auto_approve:
            found.append({
                "level": "warning", "target": target,
                "message": f"{label}: only {post - generate} minutes between the draft ({s.generate_time}) and the post ({t.post_time}), so there is little time to review it.",
            })
        at = datetime(today.year, today.month, today.day, post // 60, post % 60, tzinfo=tz)
        new_york = at.astimezone(ZoneInfo("America/New_York"))
        if new_york.hour < 7 or new_york.hour >= 20:
            found.append({
                "level": "warning", "target": target,
                "message": f"{label}: {t.post_time} here is {new_york:%I:%M %p} in New York and {at.astimezone(ZoneInfo('Europe/London')):%H:%M} in London. "
                "Most of the audience is not at work then, so the post gets little attention. Around 9 to 11 am in New York works better.",
            })
    return found
