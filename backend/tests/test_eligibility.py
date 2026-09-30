import pytest

from app.schemas import AppSettings
from app.services import store
from app.services.llm import clean_proposal, proposal_problem
from app.services.pipeline import SendError, run_cycle, send_proposal
from tests.conftest import raw_project
from tests.test_pipeline import add_prompts, configure, proposals, statuses

INR = {"code": "INR", "exchange_rate": 0.0104}
BALANCE_ERROR = (
    403,
    {
        "status": "error",
        "error_code": "ProjectExceptionCodes.BID_MINIMUM_REQUIREMENT_NOT_MET",
        "message": "To bid on this project, you must have at least $19 USD or equivalent in your account balance.",
    },
)


def inr_project(project_id: int) -> dict:
    return raw_project(project_id, currency=INR, budget={"minimum": 12500, "maximum": 37500})


async def reasons(sv):
    from sqlalchemy import select

    from app.models import Project

    async with sv.sessions() as session:
        return {p.id: p.reason for p in await session.scalars(select(Project))}


async def test_no_bids_left_stops_before_any_ai_call(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.account["account_balances"]["bids_remaining"] = 0
    fake_freelancer.projects = [raw_project(1)]
    assert await run_cycle(sv) == {"skipped": "no bids left on Freelancer"}
    assert sv.llm.select_calls == 0 and sv.llm.proposal_calls == 0


async def test_limited_account_stops_everything(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.account["limited_account"] = True
    fake_freelancer.projects = [raw_project(1)]
    assert await run_cycle(sv) == {"skipped": "Freelancer has limited this account"}


async def test_preferred_only_and_kyc_projects_are_skipped_unless_the_account_qualifies(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, skip_upgrades=[])
    fake_freelancer.account["status"]["identity_verified"] = False
    fake_freelancer.projects = [
        raw_project(1, upgrades={"pf_only": True}),
        raw_project(2, is_seller_kyc_required=True),
    ]
    await run_cycle(sv)
    assert await reasons(sv) == {1: "Preferred Freelancers only", 2: "identity verification required"}
    assert sv.llm.proposal_calls == 0

    # The same kinds of project go through once the account qualifies.
    fake_freelancer.account["preferred_freelancer"] = True
    fake_freelancer.account["status"]["identity_verified"] = True
    fake_freelancer.projects = [
        raw_project(3, upgrades={"pf_only": True}),
        raw_project(4, is_seller_kyc_required=True),
    ]
    await run_cycle(sv)
    assert {k: v for k, v in (await statuses(sv)).items() if k > 2} == {3: "proposed", 4: "proposed"}


async def test_a_balance_refusal_is_about_that_project_only(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, mode="auto")
    fake_freelancer.bid_error = BALANCE_ERROR
    fake_freelancer.projects = [inr_project(i) for i in range(1, 8)]
    await run_cycle(sv)
    # Every project is tried: this kind of refusal neither blocks the currency nor triggers holding off.
    assert [p.status for p in await proposals(sv)] == ["failed"] * 7
    async with sv.sessions() as session:
        assert (await store.get_config(session, store.RESTRICTIONS))["consecutive_failures"] == 0

    # The next project in the same currency is bid on as usual.
    fake_freelancer.bid_error = None
    fake_freelancer.projects = [inr_project(8)]
    assert await run_cycle(sv) == {"fetched": 1, "proposed": 1}
    assert [b["project_id"] for b in fake_freelancer.bids] == [8]


REFUSED = (403, {"status": "error", "error_code": "SomethingElse", "message": "Not allowed"})


async def test_a_refused_bid_does_not_stop_the_run(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, mode="auto")
    fake_freelancer.bid_error = REFUSED
    fake_freelancer.projects = [raw_project(1), raw_project(2)]
    await run_cycle(sv)
    assert [p.status for p in await proposals(sv)] == ["failed", "failed"]

    # Still running: the next project is found and bid on, and the refused ones are not retried.
    fake_freelancer.bid_error = None
    fake_freelancer.projects = [raw_project(3)]
    assert await run_cycle(sv) == {"fetched": 1, "proposed": 1}
    assert [b["project_id"] for b in fake_freelancer.bids] == [3]
    async with sv.sessions() as session:
        assert not (await store.get_settings(session)).paused


async def test_many_refusals_in_a_row_hold_off_then_resume(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, mode="auto")
    fake_freelancer.bid_error = REFUSED
    fake_freelancer.projects = [raw_project(i) for i in range(1, 8)]
    await run_cycle(sv)
    # Five refusals, then the rest of the run is left untouched and nothing is written meanwhile.
    assert [p.status for p in await proposals(sv)] == ["failed"] * 5
    assert sv.llm.proposal_calls == 5
    skipped = (await run_cycle(sv))["skipped"]
    assert "holding off until" in skipped
    async with sv.sessions() as session:
        assert not (await store.get_settings(session)).paused
        restrictions = await store.get_config(session, store.RESTRICTIONS)
        # The wait is over.
        restrictions["backoff_until"] = "2020-01-01T00:00:00+00:00"
        await store.set_config(session, store.RESTRICTIONS, restrictions)
        await session.commit()

    fake_freelancer.bid_error = None
    await run_cycle(sv)
    assert len(fake_freelancer.bids) == 2


async def test_unclean_text_is_never_sent(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1)]
    await run_cycle(sv)
    (proposal,) = await proposals(sv)
    async with sv.sessions() as session:
        stored = await session.get(type(proposal), proposal.id)
        stored.text = 'I can build this. Reach me at dev@example.com for a "quick" chat about the details of the work.' * 2
        await session.commit()
    with pytest.raises(SendError, match="needs fixing"):
        await send_proposal(sv, proposal.id)
    assert fake_freelancer.bids == []


def test_clean_proposal_removes_quotes_markdown_and_wrappers():
    raw = (
        "Here is the proposal:\n"
        '"**You need a React dashboard** that your team can “actually” use.\n\n\n\n'
        "## My approach\n"
        "- Build the charts with `Recharts`\n"
        "* Connect the REST API\n"
        "I’ve done this before.  Let's talk.\"\n"
        "</proposal>"
    )
    assert clean_proposal(raw) == (
        "You need a React dashboard that your team can actually use.\n\n"
        "My approach\n"
        "Build the charts with Recharts\n"
        "Connect the REST API\n"
        "I've done this before. Let's talk."
    )


def test_proposal_problem_flags_what_cleaning_cannot_fix():
    s = AppSettings()
    body = "I will build the dashboard in React and connect it to your API within the week. " * 2
    assert proposal_problem(body, s) is None
    assert "stray formatting" in proposal_problem(body + 'He said "yes".', s)
    assert "email" in proposal_problem(body + "Mail me: a.b@mail.com", s)
    assert "phone" in proposal_problem(body + "Call +92 300 1234567", s)
    # Ordinary numbers are not phone numbers.
    assert proposal_problem(body + "Budget 12,500 to 37,500 INR, 2019 - 2024, 80+ PageSpeed, C# and Node 20.", s) is None
