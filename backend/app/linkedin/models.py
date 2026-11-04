"""Tables of the LinkedIn service. They share the database with the other services but no rows."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base, UTCDateTime, utcnow

PERSONAL = "personal"
COMPANY = "company"
TARGETS = (PERSONAL, COMPANY)


class PostStatus:
    DRAFT = "draft"  # written, waiting for review
    APPROVED = "approved"  # goes out at scheduled_for
    POSTING = "posting"  # claimed by a run that is publishing it
    POSTED = "posted"
    FAILED = "failed"  # LinkedIn refused or the request failed
    REJECTED = "rejected"  # thrown away in the dashboard


class LinkedInAccount(Base):
    """The LinkedIn identity posts go out as: the person, or the company page. Tokens are encrypted."""

    __tablename__ = "linkedin_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(10), unique=True)  # personal | company
    name: Mapped[str] = mapped_column(String(200), default="")
    # urn:li:person:<id> or urn:li:organization:<id>
    author_urn: Mapped[str] = mapped_column(String(100), default="")
    access_token: Mapped[str] = mapped_column(Text, default="")
    # LinkedIn gives no refresh token to ordinary apps: the token lasts 60 days, then it is connected again.
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    scopes: Mapped[str] = mapped_column(Text, default="")
    expiry_warned: Mapped[bool] = mapped_column(Boolean, default=False)
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LinkedInConfig(Base):
    """One row (id 1): the settings JSON and the logo used on posters."""

    __tablename__ = "linkedin_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    logo: Mapped[bytes | None] = mapped_column(LargeBinary)
    logo_type: Mapped[str] = mapped_column(String(50), default="")


class LinkedInPost(Base):
    __tablename__ = "linkedin_posts"
    __table_args__ = (
        UniqueConstraint("target", "post_date", "slot"),
        Index("ix_linkedin_posts_status_scheduled", "status", "scheduled_for"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(10))
    # The calendar day (in the configured time zone) this post is for, and which of that day's posts it is.
    post_date: Mapped[date] = mapped_column(Date)
    slot: Mapped[int] = mapped_column(Integer, default=0)
    pillar: Mapped[str] = mapped_column(String(60), default="")
    topic: Mapped[str] = mapped_column(String(300), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    first_comment: Mapped[str] = mapped_column(Text, default="")
    poster_spec: Mapped[dict | None] = mapped_column(JSONB)
    poster: Mapped[bytes | None] = mapped_column(LargeBinary)
    alt_text: Mapped[str] = mapped_column(String(500), default="")
    signals: Mapped[dict] = mapped_column(JSONB, default=dict)  # what the topic was chosen from
    status: Mapped[str] = mapped_column(String(10), default=PostStatus.DRAFT, index=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(UTCDateTime)
    posted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    linkedin_urn: Mapped[str] = mapped_column(String(100), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class LinkedInCache(Base):
    """Things fetched from outside that are reused for a while: the day's research and the company website text."""

    __tablename__ = "linkedin_cache"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
