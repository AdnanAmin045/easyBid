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


COUNTRY_LOOKUP: dict[str, tuple[str, str]] = {
    "af": ("Afghanistan", "AF"), "afghanistan": ("Afghanistan", "AF"),
    "al": ("Albania", "AL"), "albania": ("Albania", "AL"),
    "dz": ("Algeria", "DZ"), "algeria": ("Algeria", "DZ"),
    "ar": ("Argentina", "AR"), "argentina": ("Argentina", "AR"),
    "am": ("Armenia", "AM"), "armenia": ("Armenia", "AM"),
    "au": ("Australia", "AU"), "australia": ("Australia", "AU"),
    "at": ("Austria", "AT"), "austria": ("Austria", "AT"),
    "az": ("Azerbaijan", "AZ"), "azerbaijan": ("Azerbaijan", "AZ"),
    "bh": ("Bahrain", "BH"), "bahrain": ("Bahrain", "BH"),
    "bd": ("Bangladesh", "BD"), "bangladesh": ("Bangladesh", "BD"),
    "by": ("Belarus", "BY"), "belarus": ("Belarus", "BY"),
    "be": ("Belgium", "BE"), "belgium": ("Belgium", "BE"),
    "br": ("Brazil", "BR"), "brazil": ("Brazil", "BR"),
    "bg": ("Bulgaria", "BG"), "bulgaria": ("Bulgaria", "BG"),
    "ca": ("Canada", "CA"), "canada": ("Canada", "CA"),
    "cl": ("Chile", "CL"), "chile": ("Chile", "CL"),
    "cn": ("China", "CN"), "china": ("China", "CN"),
    "co": ("Colombia", "CO"), "colombia": ("Colombia", "CO"),
    "hr": ("Croatia", "HR"), "croatia": ("Croatia", "HR"),
    "cy": ("Cyprus", "CY"), "cyprus": ("Cyprus", "CY"),
    "cz": ("Czech Republic", "CZ"), "czechia": ("Czech Republic", "CZ"), "czech republic": ("Czech Republic", "CZ"),
    "dk": ("Denmark", "DK"), "denmark": ("Denmark", "DK"),
    "eg": ("Egypt", "EG"), "egypt": ("Egypt", "EG"),
    "ee": ("Estonia", "EE"), "estonia": ("Estonia", "EE"),
    "fi": ("Finland", "FI"), "finland": ("Finland", "FI"),
    "fr": ("France", "FR"), "france": ("France", "FR"),
    "ge": ("Georgia", "GE"), "georgia": ("Georgia", "GE"),
    "de": ("Germany", "DE"), "germany": ("Germany", "DE"),
    "gh": ("Ghana", "GH"), "ghana": ("Ghana", "GH"),
    "gr": ("Greece", "GR"), "greece": ("Greece", "GR"),
    "hk": ("Hong Kong", "HK"), "hong kong": ("Hong Kong", "HK"),
    "hu": ("Hungary", "HU"), "hungary": ("Hungary", "HU"),
    "in": ("India", "IN"), "india": ("India", "IN"),
    "id": ("Indonesia", "ID"), "indonesia": ("Indonesia", "ID"),
    "ir": ("Iran", "IR"), "iran": ("Iran", "IR"),
    "iq": ("Iraq", "IQ"), "iraq": ("Iraq", "IQ"),
    "ie": ("Ireland", "IE"), "ireland": ("Ireland", "IE"),
    "il": ("Israel", "IL"), "israel": ("Israel", "IL"),
    "it": ("Italy", "IT"), "italy": ("Italy", "IT"),
    "jp": ("Japan", "JP"), "japan": ("Japan", "JP"),
    "jo": ("Jordan", "JO"), "jordan": ("Jordan", "JO"),
    "kz": ("Kazakhstan", "KZ"), "kazakhstan": ("Kazakhstan", "KZ"),
    "ke": ("Kenya", "KE"), "kenya": ("Kenya", "KE"),
    "kw": ("Kuwait", "KW"), "kuwait": ("Kuwait", "KW"),
    "lb": ("Lebanon", "LB"), "lebanon": ("Lebanon", "LB"),
    "my": ("Malaysia", "MY"), "malaysia": ("Malaysia", "MY"),
    "mx": ("Mexico", "MX"), "mexico": ("Mexico", "MX"),
    "ma": ("Morocco", "MA"), "morocco": ("Morocco", "MA"),
    "np": ("Nepal", "NP"), "nepal": ("Nepal", "NP"),
    "nl": ("Netherlands", "NL"), "netherlands": ("Netherlands", "NL"),
    "nz": ("New Zealand", "NZ"), "new zealand": ("New Zealand", "NZ"),
    "ng": ("Nigeria", "NG"), "nigeria": ("Nigeria", "NG"),
    "no": ("Norway", "NO"), "norway": ("Norway", "NO"),
    "om": ("Oman", "OM"), "oman": ("Oman", "OM"),
    "pk": ("Pakistan", "PK"), "pakistan": ("Pakistan", "PK"),
    "ps": ("Palestine", "PS"), "palestine": ("Palestine", "PS"),
    "ph": ("Philippines", "PH"), "philippines": ("Philippines", "PH"),
    "pl": ("Poland", "PL"), "poland": ("Poland", "PL"),
    "pt": ("Portugal", "PT"), "portugal": ("Portugal", "PT"),
    "qa": ("Qatar", "QA"), "qatar": ("Qatar", "QA"),
    "ro": ("Romania", "RO"), "romania": ("Romania", "RO"),
    "ru": ("Russia", "RU"), "russia": ("Russia", "RU"),
    "sa": ("Saudi Arabia", "SA"), "saudi arabia": ("Saudi Arabia", "SA"),
    "rs": ("Serbia", "RS"), "serbia": ("Serbia", "RS"),
    "sg": ("Singapore", "SG"), "singapore": ("Singapore", "SG"),
    "za": ("South Africa", "ZA"), "south africa": ("South Africa", "ZA"),
    "kr": ("South Korea", "KR"), "south korea": ("South Korea", "KR"), "korea": ("South Korea", "KR"),
    "es": ("Spain", "ES"), "spain": ("Spain", "ES"),
    "lk": ("Sri Lanka", "LK"), "sri lanka": ("Sri Lanka", "LK"),
    "se": ("Sweden", "SE"), "sweden": ("Sweden", "SE"),
    "ch": ("Switzerland", "CH"), "switzerland": ("Switzerland", "CH"),
    "tw": ("Taiwan", "TW"), "taiwan": ("Taiwan", "TW"),
    "th": ("Thailand", "TH"), "thailand": ("Thailand", "TH"),
    "tn": ("Tunisia", "TN"), "tunisia": ("Tunisia", "TN"),
    "tr": ("Turkey", "TR"), "turkey": ("Turkey", "TR"), "turkiye": ("Turkey", "TR"),
    "ua": ("Ukraine", "UA"), "ukraine": ("Ukraine", "UA"),
    "ae": ("United Arab Emirates", "AE"), "united arab emirates": ("United Arab Emirates", "AE"), "uae": ("United Arab Emirates", "AE"),
    "gb": ("United Kingdom", "GB"), "united kingdom": ("United Kingdom", "GB"), "uk": ("United Kingdom", "GB"),
    "us": ("United States", "US"), "united states": ("United States", "US"), "usa": ("United States", "US"),
    "ve": ("Venezuela", "VE"), "venezuela": ("Venezuela", "VE"),
    "vn": ("Vietnam", "VN"), "vietnam": ("Vietnam", "VN"),
}


def normalize_country(val: str) -> tuple[str, str]:
    cleaned = (val or "").strip().lower()
    if cleaned in COUNTRY_LOOKUP:
        return COUNTRY_LOOKUP[cleaned]
    return (val.strip(), val.strip().upper() if len(val.strip()) == 2 else "")


def matches_excluded_country(p_country: str, p_code: str, exclude_list: list[str]) -> str | None:
    """Return the matched country name if project matches any excluded country, or None."""
    p_name_norm, p_code_norm = normalize_country(p_country)
    p_codes = {c.lower() for c in (p_code, p_code_norm) if c}
    p_names = {n.lower() for n in (p_country, p_name_norm) if n}

    for excluded in exclude_list:
        ex = excluded.strip()
        if not ex:
            continue
        ex_name, ex_code = normalize_country(ex)
        ex_lower = ex.lower()
        if (
            (ex_code and ex_code.lower() in p_codes)
            or (ex_name and ex_name.lower() in p_names)
            or ex_lower in p_codes
            or ex_lower in p_names
        ):
            return ex_name or p_name_norm or p_country or ex
    return None


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

    # Country exclusions
    if s.exclude_countries:
        client = getattr(project, "client_info", None) or {}
        p_country = (client.get("country") or "").strip()
        p_code = (client.get("country_code") or "").strip()
        if not p_country and not p_code and project.currency:
            from app.services.freelancer import CURRENCY_COUNTRY_MAP
            if project.currency in CURRENCY_COUNTRY_MAP:
                p_country, p_code = CURRENCY_COUNTRY_MAP[project.currency]

        if p_country or p_code:
            match = matches_excluded_country(p_country, p_code, s.exclude_countries)
            if match:
                return f"excluded country: {match}"

    # Client qualifications
    client = getattr(project, "client_info", None) or {}
    if s.client_payment_verified and not client.get("payment_verified"):
        return "client payment method not verified"
    if s.client_min_hires > 0 and client.get("hires", 0) < s.client_min_hires:
        hires = client.get("hires", 0)
        return f"client has only {hires} hires (minimum {s.client_min_hires})"
    if s.client_min_rating > 0:
        rating = client.get("rating", 0.0)
        hires = client.get("hires", 0)
        if hires > 0 and rating < s.client_min_rating:
            return f"client rating {rating:.1f} below minimum {s.client_min_rating:.1f}"
    if s.client_identity_verified and not client.get("identity_verified"):
        return "client identity not verified"
    if s.client_email_verified and not client.get("email_verified"):
        return "client email not verified"
    if s.client_deposit_made and not client.get("deposit_made"):
        return "client deposit not made"

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
