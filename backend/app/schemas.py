from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PromptKind = Literal["selection", "proposal"]
Mode = Literal["manual", "semi", "auto"]


class AppSettings(BaseModel):
    """Everything the dashboard can change at runtime. Stored as one JSON document."""

    # Control
    paused: bool = True  # kill switch: nothing is fetched or sent while true
    mode: Mode = "manual"
    poll_interval_seconds: int = Field(60, ge=30, le=3600)
    max_projects_per_cycle: int = Field(15, ge=1, le=50)
    daily_bid_cap: int = Field(10, ge=0, le=500)
    semi_auto_min_score: int = Field(75, ge=0, le=100)

    # Skills: projects tagged with any of `skill_ids` are fetched
    skill_ids: list[int] = []
    skill_names: list[str] = []
    # How many of a project's skill tags must be mine, so one loose tag is not enough
    min_skill_matches: int = Field(2, ge=0, le=20)
    # Share of a project's skill tags that must be mine, so a few matches among many foreign tags are not enough
    min_skill_match_percent: int = Field(40, ge=0, le=100)
    # A project tagged with any of these is dropped
    blocked_skill_ids: list[int] = []
    blocked_skill_names: list[str] = []

    # Hard rules
    project_types: list[Literal["fixed", "hourly"]] = ["fixed", "hourly"]
    currencies: list[str] = []  # empty = any
    languages: list[str] = ["en"]  # empty = any
    min_fixed_budget: float = Field(50, ge=0)
    min_hourly_rate: float = Field(10, ge=0)
    max_bid_count: int = Field(40, ge=0)
    max_age_minutes: int = Field(60, ge=1)
    min_score: int = Field(0, ge=0, le=100)
    exclude_keywords: list[str] = []
    skip_upgrades: list[str] = ["NDA"]

    # Pricing
    fixed_budget_position: float = Field(0.6, ge=0, le=1)  # 0 = budget minimum, 1 = maximum
    hourly_rate: float = Field(25, ge=1)
    default_period_days: int = Field(7, ge=1, le=365)
    hourly_weekly_hours: int = Field(40, ge=1, le=168)
    milestone_percentage: int = Field(100, ge=1, le=100)

    # Proposal writing
    selection_model: str = "claude-opus-5-5"
    proposal_model: str = "claude-opus-5-5"
    # Tried in order when the model above is out of quota or busy. Models without an API key are skipped.
    selection_fallback_models: list[str] = ["gemini-flash-lite-latest"]
    proposal_fallback_models: list[str] = ["gemini-flash-lite-latest"]
    proposal_min_chars: int = Field(100, ge=1)
    proposal_max_chars: int = Field(1500, ge=100)


class LoginIn(BaseModel):
    email: str
    password: str


class TokenOut(BaseModel):
    token: str


class ProposalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    prompt_id: int | None
    text: str
    amount: float
    period: int
    model: str
    status: str
    auto: bool
    error: str | None
    freelancer_bid_id: int | None
    bid_status: str | None
    created_at: datetime
    sent_at: datetime | None


class ProjectBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    url: str
    type: str
    currency: str
    budget_min: float | None
    budget_max: float | None
    weekly_hours: int | None
    bid_count: int
    bid_avg: float | None
    skills: list[str]
    skill_ids: list[int]
    language: str | None
    upgrades: list[str]
    submitted_at: datetime | None
    status: str
    score: int | None
    reason: str | None
    created_at: datetime


class ProjectOut(ProjectBrief):
    proposal: ProposalOut | None = None


class ProposalWithProject(ProposalOut):
    project: ProjectBrief


class ProposalUpdate(BaseModel):
    text: str | None = Field(None, min_length=1)
    amount: float | None = Field(None, gt=0)
    period: int | None = Field(None, ge=1)


class PromptIn(BaseModel):
    kind: PromptKind
    content: str = Field(min_length=1)
    note: str = Field("", max_length=300)
    activate: bool = True


class PromptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str
    version: int
    content: str
    note: str
    is_active: bool
    created_at: datetime


class PromptTestIn(BaseModel):
    kind: PromptKind
    content: str = Field(min_length=1)
    project_id: int


class PromptTestOut(BaseModel):
    apply: bool | None = None
    reason: str | None = None
    text: str | None = None
    chars: int | None = None
    amount: float | None = None
    period: int | None = None


class ProfileItemIn(BaseModel):
    kind: Literal["bio", "skill", "project", "link"]
    title: str = Field(min_length=1, max_length=300)
    content: str = ""
    is_active: bool = True


class ProfileItemOut(ProfileItemIn):
    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: str


class SkillOut(BaseModel):
    id: int
    name: str


class LogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    level: str
    event: str
    message: str
    project_id: int | None
    created_at: datetime
