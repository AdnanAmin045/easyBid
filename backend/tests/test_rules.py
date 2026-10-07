from datetime import timedelta

from app.models import Project, utcnow
from app.schemas import AppSettings
from app.services.llm import proposal_problem
from app.services.rules import evaluate, matched_skills, price_bid


def project(**overrides) -> Project:
    values = dict(
        id=1,
        title="React app",
        description="Build it",
        type="fixed",
        currency="USD",
        budget_min=250,
        budget_max=750,
        bid_count=5,
        skills=["React.js"],
        skill_ids=[759],
        language="en",
        upgrades=[],
        submitted_at=utcnow() - timedelta(minutes=5),
    )
    values.update(overrides)
    return Project(**values)


SETTINGS = AppSettings(skill_ids=[759], exclude_keywords=["wordpress"], min_skill_matches=1)


def test_good_project_passes():
    result = evaluate(project(), SETTINGS, utcnow())
    assert result.passed
    assert result.score > 70


def test_rejections():
    now = utcnow()
    cases = {
        "budget": project(budget_min=10, budget_max=30),
        "bids already": project(bid_count=200),
        "min ago": project(submitted_at=now - timedelta(hours=5)),
        "excluded keyword": project(title="WordPress theme fix"),
        "upgrade not allowed": project(upgrades=["NDA"]),
        "language": project(language="es"),
        "hourly rate": project(type="hourly", budget_min=2, budget_max=5),
    }
    for expected, p in cases.items():
        result = evaluate(p, SETTINGS, now)
        assert not result.passed
        assert expected in result.reason


def test_skill_matching():
    s = AppSettings(skill_ids=[759, 500], blocked_skill_ids=[3], min_skill_matches=2)
    loose = project(skills=["Telemarketing", "Lead Generation", "Sales", "React.js"], skill_ids=[1, 2, 4, 759])
    result = evaluate(loose, s, utcnow())
    assert not result.passed and "only 1 of my skills match" in result.reason and "React.js" in result.reason

    blocked = project(skills=["React.js", "PHP"], skill_ids=[759, 3])
    assert "blocked skill: PHP" in evaluate(blocked, s, utcnow()).reason

    # Two matches, but most of the tags are someone else's work.
    diluted = project(
        skills=["React.js", "Node.js", "Instagram Ads", "Facebook Ads", "Advertising", "Digital Marketing"],
        skill_ids=[759, 500, 11, 12, 13, 14],
    )
    assert "only 2 of 6 skill tags are mine (33%, minimum 40%)" in evaluate(diluted, s, utcnow()).reason

    strong = project(skills=["React.js", "Node.js", "AWS"], skill_ids=[759, 500, 9])
    assert evaluate(strong, s, utcnow()).passed
    assert matched_skills(strong, s) == ["React.js", "Node.js"]


def test_min_score_rejects():
    result = evaluate(project(skill_ids=[1, 2, 3, 4]), AppSettings(skill_ids=[759], min_score=90, min_skill_matches=0, min_skill_match_percent=0), utcnow())
    assert not result.passed and "score" in result.reason


def test_pricing():
    s = AppSettings(fixed_budget_position=0.5, hourly_rate=25, default_period_days=7)
    assert price_bid(project(), s) == (500.0, 7)
    assert price_bid(project(budget_min=30, budget_max=None), s) == (30.0, 7)
    # Hourly: our rate, clamped into the client's range; period is weekly hours.
    assert price_bid(project(type="hourly", budget_min=8, budget_max=15, weekly_hours=20), s) == (15.0, 20)
    assert price_bid(project(type="hourly", budget_min=15, budget_max=50), s) == (25.0, 40)
    # $25/hour quoted in a currency worth $0.0125 per unit.
    assert price_bid(project(type="hourly", budget_min=750, budget_max=2500, usd_rate=0.0125), s) == (2000.0, 40)


def test_budget_minimum_is_compared_in_usd():
    inr = project(currency="INR", budget_min=600, budget_max=1500, usd_rate=0.012)
    result = evaluate(inr, SETTINGS, utcnow())
    assert not result.passed and "budget $18" in result.reason


def test_proposal_validation():
    s = AppSettings()
    assert proposal_problem("x" * 300, s) is None
    assert "too short" in proposal_problem("hi", s)
    assert "too long" in proposal_problem("x" * 2000, s)
    assert "placeholder" in proposal_problem("Hello [Your Name], " + "x" * 200, s)
