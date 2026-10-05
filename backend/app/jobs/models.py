"""Tables of the Jobs service. They share the database with the freelance service but no rows."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base, UTCDateTime, utcnow


class ApplicationStatus:
    DRAFT = "draft"  # written, waiting for review
    SENDING = "sending"  # claimed for sending
    SENT = "sent"
    FAILED = "failed"  # Gmail refused or the request failed


class JobProfileItem(Base):
    __tablename__ = "job_profile_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20))  # summary | experience | project | skill | education | link
    title: Mapped[str] = mapped_column(String(300))
    content: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobResume(Base):
    __tablename__ = "job_resumes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))  # e.g. "Full-stack CV"
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    data: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobPrompt(Base):
    __tablename__ = "job_prompts"
    __table_args__ = (UniqueConstraint("kind", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # application
    version: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(String(300), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class JobApplication(Base):
    __tablename__ = "job_applications"
    __table_args__ = (Index("ix_job_applications_to_email_sent_at", "to_email", "sent_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(20), default=ApplicationStatus.DRAFT, index=True)
    company: Mapped[str] = mapped_column(String(200), default="")
    role: Mapped[str] = mapped_column(String(200), default="")
    location: Mapped[str] = mapped_column(String(200), default="")
    source_text: Mapped[str] = mapped_column(Text)  # the job description as pasted
    details: Mapped[dict] = mapped_column(JSONB, default=dict)  # everything else extracted from it
    to_email: Mapped[str] = mapped_column(String(320), default="")
    cc: Mapped[list] = mapped_column(JSONB, default=list)
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("job_resumes.id", ondelete="SET NULL"))
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("job_prompts.id", ondelete="SET NULL"))
    model: Mapped[str] = mapped_column(String(60), default="")
    gmail_message_id: Mapped[str | None] = mapped_column(String(100))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    resume: Mapped[JobResume | None] = relationship(lazy="selectin")

