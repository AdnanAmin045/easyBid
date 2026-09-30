from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


UTCDateTime = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


class ProjectStatus:
    NEW = "new"  # fetched, not processed yet
    PROCESSING = "processing"  # claimed by a pipeline run
    FILTERED = "filtered"  # rejected by hard rules
    SKIPPED = "skipped"  # rejected by the selection prompt
    PROPOSED = "proposed"  # proposal exists (pending, sent, rejected or failed)
    ERROR = "error"  # pipeline failed on this project


class ProposalStatus:
    PENDING = "pending"  # waiting for approval
    SENDING = "sending"  # claimed for submission
    SENT = "sent"
    REJECTED = "rejected"  # rejected in the dashboard
    FAILED = "failed"  # Freelancer refused or the request failed


class Project(Base):
    __tablename__ = "projects"
    # Trigram indexes keep "contains" search fast as the table grows.
    __table_args__ = (
        Index("ix_projects_title_trgm", "title", postgresql_using="gin", postgresql_ops={"title": "gin_trgm_ops"}),
        Index(
            "ix_projects_description_trgm",
            "description",
            postgresql_using="gin",
            postgresql_ops={"description": "gin_trgm_ops"},
        ),
    )

    # Freelancer project id
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    url: Mapped[str] = mapped_column(String(500), default="")
    type: Mapped[str] = mapped_column(String(20), default="fixed")
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    # USD value of one unit of the project currency
    usd_rate: Mapped[float] = mapped_column(Float, default=1.0)
    budget_min: Mapped[float | None] = mapped_column(Float)
    budget_max: Mapped[float | None] = mapped_column(Float)
    weekly_hours: Mapped[int | None] = mapped_column(Integer)
    bid_count: Mapped[int] = mapped_column(Integer, default=0)
    bid_avg: Mapped[float | None] = mapped_column(Float)
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    skill_ids: Mapped[list] = mapped_column(JSONB, default=list)
    language: Mapped[str | None] = mapped_column(String(10))
    upgrades: Mapped[list] = mapped_column(JSONB, default=list)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    status: Mapped[str] = mapped_column(String(20), default=ProjectStatus.NEW, index=True)
    score: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    proposal: Mapped["Proposal | None"] = relationship(back_populates="project", uselist=False, lazy="selectin")


class Prompt(Base):
    __tablename__ = "prompts"
    __table_args__ = (UniqueConstraint("kind", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # selection | proposal
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ProfileItem(Base):
    __tablename__ = "profile_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # bio | skill | project | link
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Proposal(Base):
    __tablename__ = "proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), unique=True)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("prompts.id", ondelete="SET NULL"))
    text: Mapped[str] = mapped_column(Text)
    amount: Mapped[float] = mapped_column(Float)
    period: Mapped[int] = mapped_column(Integer)
    model: Mapped[str] = mapped_column(String(60), default="")
    status: Mapped[str] = mapped_column(String(20), default=ProposalStatus.PENDING, index=True)
    auto: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text)
    freelancer_bid_id: Mapped[int | None] = mapped_column(BigInteger)
    bid_status: Mapped[str | None] = mapped_column(String(30))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)

    project: Mapped[Project] = relationship(back_populates="proposal", lazy="selectin")


class AppConfig(Base):
    """Key/value store: 'settings', 'account' and 'runtime'."""

    __tablename__ = "app_config"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class EventLog(Base):
    __tablename__ = "event_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(10), default="info")
    event: Mapped[str] = mapped_column(String(50), index=True)
    message: Mapped[str] = mapped_column(Text)
    project_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
