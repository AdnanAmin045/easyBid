"""Tables of bulk outreach: campaigns, their recipients, saved templates and the do-not-contact list."""

from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.jobs.models import JobResume
from app.models import Base, UTCDateTime, utcnow


class CampaignStatus:
    DRAFT = "draft"  # being set up, nothing is sent
    RUNNING = "running"
    PAUSED = "paused"  # by the user, or by a safety rule (see pause_reason)
    COMPLETED = "completed"  # every recipient has an outcome
    CANCELLED = "cancelled"


class RecipientStatus:
    PENDING = "pending"
    SENDING = "sending"  # claimed by the sender
    SENT = "sent"
    REPLIED = "replied"  # a person answered in the thread
    BOUNCED = "bounced"  # Gmail could not deliver it
    FAILED = "failed"
    SKIPPED = "skipped"  # held back: suppressed, contacted recently, bad domain, cancelled

    # A message left Gmail for these.
    DELIVERED = (SENT, REPLIED, BOUNCED)


class Campaign(Base):
    __tablename__ = "outreach_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(20), default=CampaignStatus.DRAFT, index=True)
    pause_reason: Mapped[str] = mapped_column(String(300), default="")
    # template: one subject/body with {{variables}} for everyone. ai: the model writes each email from ai_brief.
    mode: Mapped[str] = mapped_column(String(10), default="template")
    subject_template: Mapped[str] = mapped_column(String(300), default="")
    body_template: Mapped[str] = mapped_column(Text, default="")
    ai_brief: Mapped[str] = mapped_column(Text, default="")
    footer: Mapped[str] = mapped_column(Text, default="")  # e.g. an opt-out line
    append_signature: Mapped[bool] = mapped_column(Boolean, default=True)
    resume_id: Mapped[int | None] = mapped_column(ForeignKey("job_resumes.id", ondelete="SET NULL"))
    # Which Gmail the campaign sends from; None means the default account.
    gmail_account_id: Mapped[int | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="SET NULL"))
    attach_first: Mapped[bool] = mapped_column(Boolean, default=True)  # attach the CV to the first email

    # Pacing: a random wait between two emails, inside a daily window, never more than daily_limit in 24 hours.
    min_delay_seconds: Mapped[int] = mapped_column(Integer, default=45)
    max_delay_seconds: Mapped[int] = mapped_column(Integer, default=150)
    daily_limit: Mapped[int] = mapped_column(Integer, default=40)
    window_start_hour: Mapped[int] = mapped_column(Integer, default=9)
    window_end_hour: Mapped[int] = mapped_column(Integer, default=18)
    timezone: Mapped[str] = mapped_column(String(60), default="UTC")
    weekdays_only: Mapped[bool] = mapped_column(Boolean, default=True)
    ramp_up: Mapped[bool] = mapped_column(Boolean, default=True)  # 10 emails on day one, 10 more each day
    # Follow-ups: [{"days": 3, "subject": "", "body": "..."}], each sent `days` after the previous email to
    # everyone who has not replied. An empty subject means "Re: <the first subject>", in the same thread.
    followups: Mapped[list] = mapped_column(JSONB, default=list)

    next_send_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    resume: Mapped[JobResume | None] = relationship(lazy="selectin")


class Recipient(Base):
    __tablename__ = "outreach_recipients"
    __table_args__ = (
        UniqueConstraint("campaign_id", "email"),
        Index("ix_outreach_recipients_queue", "campaign_id", "status", "position"),
        Index("ix_outreach_recipients_email_sent_at", "email", "sent_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("outreach_campaigns.id", ondelete="CASCADE"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    email: Mapped[str] = mapped_column(String(320))
    name: Mapped[str] = mapped_column(String(200), default="")
    company: Mapped[str] = mapped_column(String(200), default="")
    fields: Mapped[dict] = mapped_column(JSONB, default=dict)  # every other column of the imported sheet
    # Their own content, from the sheet or the AI. Empty means "use the campaign template".
    subject: Mapped[str] = mapped_column(String(300), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default=RecipientStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # Set when the user chose to write to an address that was held back as recently contacted.
    allow_recent: Mapped[bool] = mapped_column(Boolean, default=False)
    retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    error: Mapped[str | None] = mapped_column(Text)
    # The mailbox the first email went from; the thread, the follow-ups and the reply checks all belong to it.
    gmail_account_id: Mapped[int | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="SET NULL"))
    gmail_message_id: Mapped[str | None] = mapped_column(String(100))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(100))
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # the first email
    # Follow-up bookkeeping. last_contact_at is the latest email of any kind and drives the limits and the delays.
    last_contact_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    followups_sent: Mapped[int] = mapped_column(Integer, default=0)  # steps done or skipped
    followup_errors: Mapped[int] = mapped_column(Integer, default=0)
    sent_subject: Mapped[str] = mapped_column(String(300), default="")
    rfc_id: Mapped[str] = mapped_column(String(300), default="")  # Message-ID header of the latest email
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # last look for a reply or bounce
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class OutreachTemplate(Base):
    __tablename__ = "outreach_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)


class Suppression(Base):
    """Addresses that must never be written to again."""

    __tablename__ = "outreach_suppressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    reason: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
