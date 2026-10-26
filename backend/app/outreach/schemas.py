from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.jobs.schemas import FollowUp, ResumeOut

Mode = Literal["template", "ai"]


class OutreachSettings(BaseModel):
    """Stored as one JSON document in app_config under 'outreach_settings'. They cover every campaign."""

    # Gmail allows 500 a day for a personal account; this stays well below it. Job applications count too.
    daily_limit: int = Field(60, ge=1, le=400)
    # Seconds between any two sends from the account, whatever campaign they belong to.
    min_gap_seconds: int = Field(20, ge=5, le=600)
    # Do not write again to an address that was sent something within this many days (0 turns it off).
    skip_recent_days: int = Field(30, ge=0, le=365)
    # A campaign pauses itself when this share of what it sent bounced (checked from 10 emails on).
    bounce_pause_percent: int = Field(8, ge=1, le=100)
    model: str = "gemini-3.5-flash"

    # What a new campaign starts with. Each campaign keeps its own copy, so changing these never touches a running one.
    default_min_delay_seconds: int = Field(45, ge=15, le=3600)
    default_max_delay_seconds: int = Field(150, ge=15, le=7200)
    default_campaign_daily_limit: int = Field(40, ge=1, le=400)
    default_window_start_hour: int = Field(9, ge=0, le=23)
    default_window_end_hour: int = Field(18, ge=1, le=24)
    default_timezone: str = "UTC"
    default_weekdays_only: bool = True
    default_ramp_up: bool = True

    @field_validator("default_timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown time zone '{value}'. Use a name such as Asia/Karachi or Europe/London") from None
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.default_max_delay_seconds < self.default_min_delay_seconds:
            raise ValueError("The longest wait must not be shorter than the shortest wait")
        if self.default_window_end_hour <= self.default_window_start_hour:
            raise ValueError("The sending window must end after it starts")
        return self


class CampaignIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    mode: Mode = "template"
    subject_template: str = Field("", max_length=300)
    body_template: str = Field("", max_length=20000)
    ai_brief: str = Field("", max_length=4000)
    footer: str = Field("", max_length=1000)
    append_signature: bool = True
    resume_id: int | None = None
    attach_first: bool = True
    min_delay_seconds: int = Field(45, ge=15, le=3600)
    max_delay_seconds: int = Field(150, ge=15, le=7200)
    daily_limit: int = Field(40, ge=1, le=400)
    window_start_hour: int = Field(9, ge=0, le=23)
    window_end_hour: int = Field(18, ge=1, le=24)
    timezone: str = "UTC"
    weekdays_only: bool = True
    ramp_up: bool = True
    followups: list[FollowUp] = Field(default=[], max_length=5)

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError(f"Unknown time zone '{value}'. Use a name such as Asia/Karachi or Europe/London") from None
        return value

    @model_validator(mode="after")
    def consistent(self):
        if self.max_delay_seconds < self.min_delay_seconds:
            raise ValueError("The longest wait must not be shorter than the shortest wait")
        if self.window_end_hour <= self.window_start_hour:
            raise ValueError("The sending window must end after it starts")
        if sum(f.days for f in self.followups) > 60:
            raise ValueError("The follow-ups must all be sent within 60 days of the first email")
        return self


class CampaignPatch(BaseModel):
    """Any subset of CampaignIn; the result is validated as a whole."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    mode: Mode | None = None
    subject_template: str | None = None
    body_template: str | None = None
    ai_brief: str | None = None
    footer: str | None = None
    append_signature: bool | None = None
    resume_id: int | None = None
    attach_first: bool | None = None
    clear_resume: bool = False
    min_delay_seconds: int | None = None
    max_delay_seconds: int | None = None
    daily_limit: int | None = None
    window_start_hour: int | None = None
    window_end_hour: int | None = None
    timezone: str | None = None
    weekdays_only: bool | None = None
    ramp_up: bool | None = None
    followups: list[FollowUp] | None = None


class CampaignBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str
    pause_reason: str
    mode: str
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime


class CampaignListItem(CampaignBrief):
    counts: dict[str, int] = {}


class CampaignOut(CampaignBrief):
    subject_template: str
    body_template: str
    ai_brief: str
    footer: str
    append_signature: bool
    resume_id: int | None
    attach_first: bool = True
    resume: ResumeOut | None
    min_delay_seconds: int
    max_delay_seconds: int
    daily_limit: int
    window_start_hour: int
    window_end_hour: int
    timezone: str
    weekdays_only: bool
    ramp_up: bool
    next_send_at: datetime | None
    followups: list[FollowUp] = []
    followups_sent: int = 0  # follow-up emails that went out
    followups_scheduled: int = 0  # people still waiting for a follow-up
    counts: dict[str, int] = {}
    sent_24h: int = 0
    # Why nothing is going out right now (outside the window, daily limit, ...), or None when it is on its way.
    waiting: str | None = None
    columns: list[str] = []


class RecipientOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    name: str
    company: str
    fields: dict
    subject: str
    body: str
    status: str
    attempts: int
    error: str | None
    sent_at: datetime | None
    last_contact_at: datetime | None
    followups_sent: int
    gmail_thread_id: str | None
    created_at: datetime


class RecipientPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str | None = None
    name: str | None = Field(None, max_length=200)
    company: str | None = Field(None, max_length=200)
    subject: str | None = Field(None, max_length=300)
    body: str | None = None
    fields: dict[str, str] | None = None


class ImportIn(BaseModel):
    text: str = Field(min_length=3, max_length=3_000_000)
    # Hold back addresses written to recently (see settings) instead of adding them as pending.
    skip_recent: bool = True
    # Look up each domain's mail server and hold back the ones that cannot receive mail.
    check_domains: bool = True


class RejectedRow(BaseModel):
    line: int
    value: str
    reason: str


class ImportOut(BaseModel):
    added: int
    held_back: int  # added as "skipped" with the reason shown on the row
    rejected: list[RejectedRow]
    rejected_total: int
    with_own_content: int  # rows that bring their own subject and body
    columns: list[str]


class TemplateIn(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    subject: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class TemplateOut(TemplateIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    updated_at: datetime


class GenerateIn(BaseModel):
    brief: str = Field(min_length=10, max_length=4000)
    tone: str = Field("friendly and direct", max_length=100)
    language: str = Field("English", max_length=40)
    # Extra columns of the list, so the model knows which {{variables}} it may use.
    variables: list[str] = Field(default=[], max_length=30)


class GeneratedEmail(BaseModel):
    subject: str
    body: str


class Preview(BaseModel):
    recipient_id: int
    email: str
    subject: str
    body: str
    missing: list[str]
    own_content: bool
    step: int = 0  # 0 is the first email, 1 the first follow-up, ...


class TestSendIn(BaseModel):
    recipient_id: int | None = None


class MissingVariables(BaseModel):
    id: int
    email: str
    missing: list[str]


class Check(BaseModel):
    ready: bool
    blockers: list[str]
    warnings: list[str]
    pending: int
    with_missing: int
    missing_examples: list[MissingVariables]
    # Roughly how long the pending recipients take at the current pacing, in days.
    estimated_days: float


class SuppressionIn(BaseModel):
    emails: str = Field(min_length=3, max_length=200_000)  # any text with addresses in it
    reason: str = Field("", max_length=300)


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    reason: str
    created_at: datetime
