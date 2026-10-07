"""Hard rules, scoring and pricing. Pure functions: no I/O, no AI."""

from dataclasses import dataclass
from datetime import datetime

from app.models import Project
from app.schemas import AppSettings


@dataclass
class RuleResult:
    passed: bool
    score: int
    reason: str


def _budget_usd(project: Project) -> float:
    """Top of the client's budget in USD, so one minimum works across currencies."""
    return (project.budget_max or project.budget_min or 0) * (project.usd_rate or 1)


def matched_skills(project: Project, s: AppSettings) -> list[str]:
    """Names of the project's skill tags that are in my skill set."""
    mine = set(s.skill_ids)
    return [name for skill_id, name in zip(project.skill_ids or [], project.skills or []) if skill_id in mine]


def skill_match_percent(project: Project, s: AppSettings) -> float:
    tags = project.skill_ids or []
    return len(matched_skills(project, s)) / len(tags) * 100 if tags else 0


def check_rules(project: Project, s: AppSettings, now: datetime) -> str | None:
    """Return why the project is rejected, or None if it passes every hard rule."""
    blocked = set(s.blocked_skill_ids)
    hits = [name for skill_id, name in zip(project.skill_ids or [], project.skills or []) if skill_id in blocked]
    if hits:
        return f"blocked skill: {', '.join(hits)}"
    matched = matched_skills(project, s)
    if len(matched) < s.min_skill_matches:
        return f"only {len(matched)} of my skills match (minimum {s.min_skill_matches}): {', '.join(matched) or 'none'}"
    percent = skill_match_percent(project, s)
    if project.skill_ids and percent < s.min_skill_match_percent:
        return (
            f"only {len(matched)} of {len(project.skill_ids)} skill tags are mine "
            f"({percent:.0f}%, minimum {s.min_skill_match_percent}%): {', '.join(matched) or 'none'}"
        )

    if project.type not in s.project_types:
        return f"{project.type} projects are disabled"
    if s.currencies and project.currency not in s.currencies:
        return f"currency {project.currency} not allowed"
    if s.languages and project.language and project.language not in s.languages:
        return f"language {project.language} not allowed"

    budget = _budget_usd(project)
    if project.type == "hourly" and budget < s.min_hourly_rate:
        return f"hourly rate ${budget:.0f} below minimum ${s.min_hourly_rate:g}"
    if project.type == "fixed" and budget < s.min_fixed_budget:
        return f"budget ${budget:.0f} below minimum ${s.min_fixed_budget:g}"

    if project.bid_count > s.max_bid_count:
        return f"{project.bid_count} bids already (max {s.max_bid_count})"
    if project.submitted_at:
        age = (now - project.submitted_at).total_seconds() / 60
        if age > s.max_age_minutes:
            return f"posted {age:.0f} min ago (max {s.max_age_minutes})"

    blocked = [u for u in project.upgrades if u in s.skip_upgrades]
    if blocked:
        return f"upgrade not allowed: {', '.join(blocked)}"

    text = f"{project.title}\n{project.description}".lower()
    for keyword in s.exclude_keywords:
        if keyword.strip() and keyword.strip().lower() in text:
            return f"excluded keyword: {keyword.strip()}"
    return None


def score_project(project: Project, s: AppSettings, now: datetime) -> int:
    """0-100: skill match 40, budget 20, low competition 20, freshness 20."""
    match = skill_match_percent(project, s) / 100

    floor = s.min_hourly_rate if project.type == "hourly" else s.min_fixed_budget
    # Full marks at 4x the minimum acceptable budget.
    budget = min(_budget_usd(project) / (floor * 4), 1) if floor else 1

    competition = max(1 - project.bid_count / s.max_bid_count, 0) if s.max_bid_count else 0

    freshness = 1.0
    if project.submitted_at:
        age = (now - project.submitted_at).total_seconds() / 60
        freshness = max(1 - age / s.max_age_minutes, 0)

    return round(match * 40 + budget * 20 + competition * 20 + freshness * 20)


def evaluate(project: Project, s: AppSettings, now: datetime) -> RuleResult:
    score = score_project(project, s, now)
    reason = check_rules(project, s, now)
    if reason is None and score < s.min_score:
        reason = f"score {score} below minimum {s.min_score}"
    return RuleResult(passed=reason is None, score=score, reason=reason or "")


def price_bid(project: Project, s: AppSettings) -> tuple[float, int]:
    """Return (amount, period) in the project currency. Hourly: rate and weekly hours. Fixed: total and days."""
    low = project.budget_min or 0
    high = project.budget_max or low

    if project.type == "hourly":
        amount = s.hourly_rate / (project.usd_rate or 1)  # our rate is set in USD
        if high:
            amount = min(max(amount, low), high)
        return float(round(amount)), project.weekly_hours or s.hourly_weekly_hours

    amount = low + (high - low) * s.fixed_budget_position
    amount = max(amount, low, 1)
    return float(round(amount)), s.default_period_days
