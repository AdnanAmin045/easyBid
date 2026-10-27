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


class GmailAccount(Base):
    """A Gmail mailbox emails can be sent from. Each campaign and application picks one; the first connected is the default."""

    __tablename__ = "gmail_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    # "gmail" sends through the Gmail API with a refresh token; "smtp" through any mailbox with SMTP, and reads
    # replies over IMAP. Secrets are encrypted, see app.jobs.gmail.encrypt.
    # "alias" is an address added to a Gmail under "Send mail as": emails go out through that Gmail (over HTTPS) with the
    # alias as the sender, so it shares the Gmail's connection, limits and mailbox. `parent_id` is that Gmail.
    kind: Mapped[str] = mapped_column(String(10), default="gmail")
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="CASCADE"))
    refresh_token: Mapped[str] = mapped_column(Text, default="")
    smtp_host: Mapped[str] = mapped_column(String(255), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=465)
    smtp_secure: Mapped[bool] = mapped_column(Boolean, default=True)  # TLS from the start; False means STARTTLS
    smtp_user: Mapped[str] = mapped_column(String(320), default="")
    smtp_password: Mapped[str] = mapped_column(Text, default="")
    imap_host: Mapped[str] = mapped_column(String(255), default="")
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    scopes: Mapped[str] = mapped_column(Text, default="")
    # Shown as the sender and signed under the emails; blank means the names in the Jobs settings.
    sender_name: Mapped[str] = mapped_column(String(120), default="")
    signature: Mapped[str] = mapped_column(String(1000), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    connected_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


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
    # The mailbox it was (or will be) sent from. Its thread lives there, so follow-ups and replies use the same one.
    gmail_account_id: Mapped[int | None] = mapped_column(ForeignKey("gmail_accounts.id", ondelete="SET NULL"))
    gmail_message_id: Mapped[str | None] = mapped_column(String(100))
    gmail_thread_id: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)
    # Follow-ups: [{"days": 5, "subject": "", "body": "..."}], sent `days` after the previous email while nobody replies.
    followups: Mapped[list] = mapped_column(JSONB, default=list)
    followups_sent: Mapped[int] = mapped_column(Integer, default=0)  # steps done or skipped
    followup_errors: Mapped[int] = mapped_column(Integer, default=0)
    followup_note: Mapped[str | None] = mapped_column(Text)
    followup_claim_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # set while a follow-up is being sent
    followup_retry_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    last_contact_at: Mapped[datetime | None] = mapped_column(UTCDateTime, index=True)  # latest email of any kind
    sent_subject: Mapped[str] = mapped_column(String(300), default="")
    rfc_id: Mapped[str] = mapped_column(String(300), default="")  # Message-ID header of the latest email
    outcome: Mapped[str] = mapped_column(String(10), default="")  # "", "replied" or "bounced"
    checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime)  # last look for a reply
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    resume: Mapped[JobResume | None] = relationship(lazy="selectin")

