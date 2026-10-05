import pytest
from sqlalchemy import select

from app.models import Project, Prompt, Proposal
from app.services import store
from app.services.llm import LLMError
from app.services.pipeline import SendError, run_cycle, send_proposal, sync_bids
from tests.conftest import raw_project


async def configure(sv, **settings):
    async with sv.sessions() as session:
        current = await store.get_settings(session)
        await store.save_settings(session, current.model_copy(update=settings))
        await session.commit()


async def add_prompts(sv, selection=True):
    async with sv.sessions() as session:
        session.add(Prompt(kind="proposal", version=1, content="Write a short proposal.", is_active=True))
        if selection:
            session.add(Prompt(kind="selection", version=1, content="Only React jobs.", is_active=True))
        await session.commit()


async def proposals(sv):
    async with sv.sessions() as session:
        return list(await session.scalars(select(Proposal)))


async def all_projects(sv):
    async with sv.sessions() as session:
        return list(await session.scalars(select(Project)))


async def statuses(sv):
    async with sv.sessions() as session:
        return {p.id: p.status for p in await session.scalars(select(Project))}


async def test_manual_mode_queues_without_bidding(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1)]
    summary = await run_cycle(sv)
    assert summary == {"fetched": 1, "proposed": 1}
    (proposal,) = await proposals(sv)
    assert proposal.status == "pending"
    assert proposal.amount == 550 and proposal.period == 7
    assert fake_freelancer.bids == []

    # Approving sends exactly the stored proposal from the token's account.
    await send_proposal(sv, proposal.id)
    (bid,) = fake_freelancer.bids
    assert bid["project_id"] == 1 and bid["bidder_id"] == 99 and bid["amount"] == 550
    assert bid["description"] == proposal.text
    (proposal,) = await proposals(sv)
    assert proposal.status == "sent" and proposal.freelancer_bid_id == 5000

    # A sent bid can never be sent twice.
    with pytest.raises(SendError):
        await send_proposal(sv, proposal.id)
    assert len(fake_freelancer.bids) == 1


async def test_projects_are_processed_once(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1)]
    await run_cycle(sv)
    await run_cycle(sv)
    assert sv.llm.proposal_calls == 1
    assert len(await proposals(sv)) == 1


async def test_auto_mode_bids_and_respects_daily_cap(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, mode="auto", daily_bid_cap=2)
    fake_freelancer.projects = [raw_project(i) for i in (1, 2, 3)]
    await run_cycle(sv)
    assert len(fake_freelancer.bids) == 2
    # The third project is left alone: no proposal is written once the cap is reached.
    assert [p.status for p in await proposals(sv)] == ["sent", "sent"]
    assert sorted((await statuses(sv)).values()) == ["new", "proposed", "proposed"]
    assert await run_cycle(sv) == {"skipped": "daily bid cap reached (2)"}
    assert sv.llm.proposal_calls == 2


async def test_semi_mode_only_auto_sends_high_scores(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, mode="semi", semi_auto_min_score=80)
    fake_freelancer.projects = [
        raw_project(1),
        raw_project(2, bid_stats={"bid_count": 35}, jobs=[{"id": 759, "name": "React.js"}, {"id": 3, "name": "PHP"}]),
    ]
    await run_cycle(sv)
    assert [b["project_id"] for b in fake_freelancer.bids] == [1]


async def test_rules_and_selection_stop_projects_before_ai_writes(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1, budget={"minimum": 10, "maximum": 20})]
    await run_cycle(sv)
    assert await statuses(sv) == {1: "filtered"}
    assert sv.llm.select_calls == 0  # hard rules run before any AI call

    sv.llm.apply = False
    fake_freelancer.projects = [raw_project(2)]
    await run_cycle(sv)
    assert (await statuses(sv))[2] == "skipped"
    assert sv.llm.proposal_calls == 0
    assert await proposals(sv) == []


async def test_ai_out_of_quota_keeps_projects_for_later(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1), raw_project(2)]
    sv.llm.error = LLMError("Gemini API error 429: quota exceeded", transient=True)
    summary = await run_cycle(sv)
    # The first failure rests the AI; the second project is not thrown at it.
    assert summary == {"fetched": 2, "waiting for AI": 1}
    assert sv.llm.select_calls == 1
    assert await statuses(sv) == {1: "new", 2: "new"}
    assert (await run_cycle(sv))["skipped"].startswith("AI is out of quota or busy")

    # Once the rest is over, both projects are picked up again.
    sv.llm.error = None
    async with sv.sessions() as session:
        await store.set_config(session, store.RESTRICTIONS, {})
        await session.commit()
    await run_cycle(sv)
    assert await statuses(sv) == {1: "proposed", 2: "proposed"}
    assert all(p.reason == "matches my skills" for p in await all_projects(sv))


async def test_ai_error_about_the_project_is_final(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1)]
    sv.llm.error = LLMError("The model declined this request")
    await run_cycle(sv)
    assert await statuses(sv) == {1: "error"}


async def test_no_selection_prompt_means_rules_decide(sv, fake_freelancer):
    await add_prompts(sv, selection=False)
    fake_freelancer.projects = [raw_project(1)]
    await run_cycle(sv)
    assert sv.llm.select_calls == 0
    assert await statuses(sv) == {1: "proposed"}


async def test_nothing_runs_without_a_proposal_prompt(sv, fake_freelancer):
    await configure(sv, mode="auto")
    fake_freelancer.projects = [raw_project(1)]
    assert await run_cycle(sv) == {"skipped": "no active proposal prompt"}
    assert await statuses(sv) == {}
    assert fake_freelancer.bids == []


async def test_paused_does_nothing(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1)]
    await run_cycle(sv)
    (proposal,) = await proposals(sv)
    await configure(sv, paused=True)
    assert await run_cycle(sv) == {"skipped": "paused"}
    with pytest.raises(SendError, match="paused"):
        await send_proposal(sv, proposal.id)
    assert fake_freelancer.bids == []


async def test_failed_bid_is_recorded_and_can_be_retried(sv, fake_freelancer):
    await add_prompts(sv)
    fake_freelancer.projects = [raw_project(1)]
    await run_cycle(sv)
    (proposal,) = await proposals(sv)
    fake_freelancer.bid_error = (403, {"status": "error", "message": "No bids left", "error_code": "BidLimit"})
    with pytest.raises(SendError, match="No bids left"):
        await send_proposal(sv, proposal.id)
    (proposal,) = await proposals(sv)
    assert proposal.status == "failed" and "BidLimit" in proposal.error

    fake_freelancer.bid_error = None
    await send_proposal(sv, proposal.id)
    assert (await proposals(sv))[0].status == "sent"


async def test_scheduler_heartbeat(sv):
    from app.services.pipeline import scheduler_running, tick

    async def runtime():
        async with sv.sessions() as session:
            return await store.get_config(session, store.RUNTIME)

    assert not scheduler_running(await runtime())
    await configure(sv, paused=True)
    await tick(sv, owner="worker")  # ticks while paused too, so the dashboard can tell the scheduler is alive
    assert scheduler_running(await runtime())

    # A standby scheduler leaves a live one alone...
    await tick(sv, owner="web", standby=True)
    assert (await runtime())["tick_owner"] == "worker"

    # ...takes over once it has gone quiet, and then keeps going.
    async with sv.sessions() as session:
        stale = {**await store.get_config(session, store.RUNTIME), "last_tick": "2020-01-01T00:00:00+00:00"}
        await store.set_config(session, store.RUNTIME, stale)
        await session.commit()
    await tick(sv, owner="web", standby=True)
    assert (await runtime())["tick_owner"] == "web" and scheduler_running(await runtime())
    await tick(sv, owner="web", standby=True)
    assert scheduler_running(await runtime())


async def test_sync_bids_updates_award_status(sv, fake_freelancer):
    await add_prompts(sv)
    await configure(sv, mode="auto")
    fake_freelancer.projects = [raw_project(1)]
    await run_cycle(sv)
    fake_freelancer.bid_statuses = {5000: "awarded"}
    assert await sync_bids(sv) == 1
    assert (await proposals(sv))[0].bid_status == "awarded"
    assert await sync_bids(sv) == 0
