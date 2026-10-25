from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ProfileKind = Literal["summary", "experience", "project", "skill", "education", "link"]


class FollowUp(BaseModel):
    """One follow-up: sent `days` after the previous email to someone who has not replied."""

    days: int = Field(ge=1, le=60)
    # Empty: "Re: <first subject>", so it stays in the same conversation.
    subject: str = Field("", max_length=300)
    body: str = Field(min_length=1, max_length=20000)


def check_followups(items: list[FollowUp]) -> list[FollowUp]:
    if sum(f.days for f in items) > 60:
        raise ValueError("The follow-ups must all be sent within 60 days of the first email")
    return items


class JobSettings(BaseModel):
    """Stored as one JSON document in app_config under 'jobs_settings'."""

    sender_name: str = Field("", max_length=120)
    signature: str = Field("", max_length=1000)
    model: str = "gemini-3.5-flash"
    # Personal Gmail: stay far below Google's own limit so the account is never flagged.
    daily_send_limit: int = Field(20, ge=1, le=100)
    email_min_chars: int = Field(300, ge=50)
    email_max_chars: int = Field(2500, ge=300, le=10000)
    # Warn before writing to an address or company applied to within this many days.
    duplicate_window_days: int = Field(30, ge=0, le=365)
    # Follow-ups every new application starts with; each application can change them.
    default_followups: list[FollowUp] = Field(default=[], max_length=5)

    _plan = field_validator("default_followups")(check_followups)


class EmailCheck(BaseModel):
    email: str
    valid: bool
    reason: str = ""
    applied_before: datetime | None = None


class Extraction(BaseModel):
    company: str = ""
    role: str = ""
    location: str = ""
    work_mode: str = ""  # remote | hybrid | onsite | ""
    recipient_name: str = ""
    apply_via: Literal["email", "link", "unknown"] = "unknown"
    apply_link: str = ""
    apply_instructions: list[str] = []
    required_skills: list[str] = []
    deadline: str = ""
    emails: list[EmailCheck] = []
    # Set when the AI step failed and only the text scan ran.
    warning: str = ""


class ExtractIn(BaseModel):
    text: str = Field(min_length=20, max_length=30000)


class ApplicationCreate(BaseModel):
    source_text: str = Field(min_length=20, max_length=30000)
    details: Extraction
    to_email: EmailStr
    cc: list[EmailStr] = Field(default=[], max_length=5)
    resume_id: int | None = None


class ApplicationUpdate(BaseModel):
    company: str | None = Field(None, max_length=200)
    role: str | None = Field(None, max_length=200)
    to_email: EmailStr | None = None
    cc: list[EmailStr] | None = Field(None, max_length=5)
    subject: str | None = Field(None, min_length=1, max_length=300)
    body: str | None = Field(None, min_length=1)
    resume_id: int | None = None
    clear_resume: bool = False


class FollowUpsIn(BaseModel):
    followups: list[FollowUp] = Field(default=[], max_length=5)

    _plan = field_validator("followups")(check_followups)


class SendIn(BaseModel):
    # Required to write again to an address or company applied to recently.
    allow_duplicate: bool = False


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    filename: str
    content_type: str
    size: int
    is_default: bool
    created_at: datetime


class ApplicationBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    company: str
    role: str
    location: str
    to_email: str
    subject: str
    error: str | None
    sent_at: datetime | None
    created_at: datetime
    outcome: str = ""  # "", "replied" or "bounced"


class ApplicationOut(ApplicationBrief):
    source_text: str
    details: dict
    cc: list[str]
    body: str
    resume_id: int | None
    resume: ResumeOut | None
    prompt_id: int | None
    model: str
    gmail_thread_id: str | None
    followups: list[FollowUp] = []
    followups_sent: int = 0
    followup_note: str | None = None
    last_contact_at: datetime | None = None


class ProfileItemIn(BaseModel):
    kind: ProfileKind = "experience"
    title: str = Field(min_length=1, max_length=300)
    content: str = ""
    is_active: bool = True


class ProfileItemOut(ProfileItemIn):
    model_config = ConfigDict(from_attributes=True)

    id: int


class PromptIn(BaseModel):
    content: str = Field(min_length=1)
    note: str = Field("", max_length=300)


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    version: int
    content: str
    note: str
    is_active: bool
    created_at: datetime


class GmailStatus(BaseModel):
    configured: bool  # the OAuth app is set up on the server
    connected: bool
    email: str | None = None
    connected_at: datetime | None = None
