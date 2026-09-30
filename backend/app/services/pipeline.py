"""The bidding pipeline: fetch -> hard rules -> selection prompt -> proposal prompt -> bid."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models import ProfileItem, Project, ProjectStatus, Prompt, Proposal, ProposalStatus, utcnow
from app.schemas import AppSettings
from app.services import eligibility, store
from app.services.freelancer import FreelancerClient, FreelancerError, bid_status, normalize_project
from app.services.llm import LLM, LLMError, proposal_problem
from app.services.notifier import Notifier
from app.services.rules import evaluate, price_bid

logger = logging.getLogger("easybid")

STALE_CLAIM = timedelta(minutes=15)
BID_SYNC_INTERVAL = timedelta(minutes=10)
# The scheduler records that it is alive this often; the dashboard warns when the record goes stale.
HEARTBEAT = timedelta(minutes=1)
HEARTBEAT_STALE = timedelta(minutes=3)
# One pipeline run at a time per process; database claims cover other processes.
_cycle_lock = asyncio.Lock()


class SendError(Exception):
    pass


@dataclass
class Services:
    sessions: async_sessionmaker[AsyncSession]
    freelancer: FreelancerClient
    llm: LLM
    notifier: Notifier


@dataclass
class Draft:
    text: str
    amount: float
    period: int
    prompt_id: int | None


async def get_account(
    sv: Services, session: AsyncSession, refresh: bool = False, max_age: timedelta | None = None
) -> dict:
    """The Freelancer account behind the token, cached in the database.

    Fetched again when `refresh` is set, when the cached copy is older than `max_age`,
    or when it predates the bids/balance fields (no `refreshed_at`).
    """
    account = await store.get_config(session, store.ACCOUNT)
    refreshed_at = account.get("refreshed_at")
    stale = refreshed_at is None or (
        max_age is not None and utcnow() - datetime.fromisoformat(refreshed_at) > max_age
    )
    if account and not refresh and not stale:
        return account
    account = eligibility.account_snapshot(await sv.freelancer.get_self())
    await store.set_config(session, store.ACCOUNT, account)
    await session.commit()
    return account


async def active_prompt(session: AsyncSession, kind: str) -> Prompt | None:
    return await session.scalar(select(Prompt).where(Prompt.kind == kind, Prompt.is_active))


async def active_profile(session: AsyncSession) -> list[ProfileItem]:
    rows = await session.scalars(select(ProfileItem).where(ProfileItem.is_active).order_by(ProfileItem.id))
    return list(rows)


async def bids_sent_today(session: AsyncSession) -> int:
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = await session.scalar(
        select(func.count()).where(Proposal.status == ProposalStatus.SENT, Proposal.sent_at >= midnight)
    )
    return count or 0


async def bidding_wait(session: AsyncSession, s: AppSettings) -> str | None:
    """Why no bid can go out right now, so nothing should be fetched or written. None if bids can go out."""
    if await bids_sent_today(session) >= s.daily_bid_cap:
        return f"daily bid cap reached ({s.daily_bid_cap})"
    until = (await store.get_config(session, store.RESTRICTIONS)).get("backoff_until")
    if until and utcnow() < datetime.fromisoformat(until):
        return f"holding off until {until[11:16]} UTC after repeated refused bids"
    return None


async def fetch_new_projects(sv: Services, session: AsyncSession, s: AppSettings) -> int:
    raw = await sv.freelancer.search_active_projects(s.skill_ids)
    if not raw:
        return 0
    known = set(await session.scalars(select(Project.id).where(Project.id.in_([p["id"] for p in raw]))))
    fresh = [p for p in raw if p["id"] not in known]
    session.add_all(Project(**normalize_project(p)) for p in fresh)
    await session.commit()
    return len(fresh)


async def write_draft(
    sv: Services, session: AsyncSession, project: Project, s: AppSettings, prompt_content: str | None = None
) -> Draft:
    """Price the bid and write the proposal. `prompt_content` overrides the active prompt (used by previews)."""
    prompt_id = None
    if prompt_content is None:
        prompt = await active_prompt(session, "proposal")
        if prompt is None:
            raise LLMError("No active proposal prompt. Add one on the Prompts page.")
        prompt_content, prompt_id = prompt.content, prompt.id
    amount, period = price_bid(project, s)
    text = await sv.llm.write_proposal(prompt_content, project, await active_profile(session), amount, period, s)
    return Draft(text=text, amount=amount, period=period, prompt_id=prompt_id)


async def save_draft(session: AsyncSession, project: Project, draft: Draft, s: AppSettings) -> Proposal:
    """Create the project's proposal, or replace one that has not been sent."""
    proposal = await session.scalar(select(Proposal).where(Proposal.project_id == project.id))
    if proposal is None:
        proposal = Proposal(project_id=project.id, text="", amount=0, period=0)
        session.add(proposal)
    elif proposal.status in (ProposalStatus.SENT, ProposalStatus.SENDING):
        raise SendError("A bid was already sent for this project")
    proposal.text, proposal.amount, proposal.period = draft.text, draft.amount, draft.period
    proposal.prompt_id, proposal.model = draft.prompt_id, s.proposal_model
    proposal.status, proposal.error = ProposalStatus.PENDING, None
    project.status = ProjectStatus.PROPOSED
    await session.commit()
    return proposal


async def _after_refusal(sv: Services, session: AsyncSession, proposal: Proposal, error: FreelancerError) -> None:
    """The pipeline carries on after a refused bid; many refusals in a row only hold it off for a while."""
    restrictions = await store.get_config(session, store.RESTRICTIONS)
    # A requirement of that one project says nothing about the account, so it does not count.
    counts = not eligibility.is_project_requirement(error.error_code)
    failures = restrictions.get("consecutive_failures", 0) + (1 if counts else 0)

    message = f"EasyBid: bid failed on \"{proposal.project.title}\"\n{proposal.error}"
    if failures >= eligibility.BACKOFF_AFTER_FAILURES:
        until = utcnow() + eligibility.BACKOFF
        restrictions["backoff_until"] = until.isoformat()
        note = f"{failures} refused bids in a row. Bidding resumes by itself at {until:%H:%M} UTC."
        store.log_event(session, "holding_off", note, "error")
        message += f"\n\n{note}"
        failures = 0
    restrictions["consecutive_failures"] = failures
    await store.set_config(session, store.RESTRICTIONS, restrictions)
    await session.commit()
    await sv.notifier.send(message)


async def send_proposal(sv: Services, proposal_id: int, auto: bool = False) -> Proposal:
    """Submit a proposal as a bid on Freelancer. Raises SendError if it cannot be sent."""
    async with sv.sessions() as session:
        s = await store.get_settings(session)
        if s.paused:
            raise SendError("EasyBid is paused")
        if await bids_sent_today(session) >= s.daily_bid_cap:
            raise SendError(f"Daily bid cap reached ({s.daily_bid_cap})")
        account = await get_account(sv, session)
        blocked = eligibility.account_problem(account)
        if blocked:
            raise SendError(f"Cannot bid: {blocked}")
        current = await session.get(Proposal, proposal_id)
        if current is None:
            raise SendError("Proposal not found")
        # Covers hand-edited text too: nothing unclean ever reaches a client.
        problem = proposal_problem(current.text, s)
        if problem:
            raise SendError(f"Proposal needs fixing, it is {problem}")

        # Claim the proposal so two callers can never send the same bid.
        claimed = await session.execute(
            update(Proposal)
            .where(Proposal.id == proposal_id, Proposal.status.in_([ProposalStatus.PENDING, ProposalStatus.FAILED]))
            .values(status=ProposalStatus.SENDING, auto=auto, error=None)
        )
        await session.commit()
        if claimed.rowcount != 1:
            raise SendError("Proposal is not waiting to be sent")

        proposal = await session.get(Proposal, proposal_id, populate_existing=True)
        title = proposal.project.title
        try:
            result = await sv.freelancer.place_bid(
                project_id=proposal.project_id,
                bidder_id=account["id"],
                amount=proposal.amount,
                period=proposal.period,
                milestone_percentage=s.milestone_percentage,
                description=proposal.text,
            )
        except FreelancerError as e:
            proposal.status = ProposalStatus.FAILED
            proposal.error = str(e) if e.status_code else f"Outcome unknown, check Freelancer before retrying: {e}"
            store.log_event(session, "bid_failed", f"{title}: {proposal.error}", "error", proposal.project_id)
            await _after_refusal(sv, session, proposal, e)
            raise SendError(proposal.error) from e

        proposal.status = ProposalStatus.SENT
        proposal.sent_at = utcnow()
        proposal.freelancer_bid_id = result.get("id")
        proposal.bid_status = "active"
        store.log_event(
            session, "bid_sent", f"{title}: {proposal.amount:g} {proposal.project.currency}", "info", proposal.project_id
        )
        restrictions = await store.get_config(session, store.RESTRICTIONS)
        await store.set_config(session, store.RESTRICTIONS, {**restrictions, "consecutive_failures": 0})
        if account.get("bids_remaining"):
            await store.set_config(session, store.ACCOUNT, {**account, "bids_remaining": account["bids_remaining"] - 1})
        await session.commit()
        await sv.notifier.send(
            f"EasyBid: bid sent on \"{title}\" ({proposal.amount:g} {proposal.project.currency})\n{proposal.project.url}"
        )
        return proposal


async def process_project(sv: Services, project_id: int) -> str:
    """Run one fetched project through rules, selection and proposal. Returns its final status."""
    async with sv.sessions() as session:
        claimed = await session.execute(
            update(Project)
            .where(Project.id == project_id, Project.status == ProjectStatus.NEW)
            .values(status=ProjectStatus.PROCESSING)
        )
        await session.commit()
        if claimed.rowcount != 1:
            return "claimed elsewhere"

        project = await session.get(Project, project_id, populate_existing=True)
        s = await store.get_settings(session)

        result = evaluate(project, s, utcnow())
        project.score = result.score
        reason = result.reason
        if result.passed:
            # Rules passed (skills first); now: is this account allowed to bid on it?
            account = await get_account(sv, session)
            reason = eligibility.check_eligibility(project, account)
        if reason:
            project.status, project.reason = ProjectStatus.FILTERED, reason
            await session.commit()
            return project.status

        try:
            selection_prompt = await active_prompt(session, "selection")
            if selection_prompt:
                decision = await sv.llm.select(selection_prompt.content, project, await active_profile(session), s)
                project.reason = decision.reason
                if not decision.apply:
                    project.status = ProjectStatus.SKIPPED
                    await session.commit()
                    return project.status
            draft = await write_draft(sv, session, project, s)
        except LLMError as e:
            project.status, project.reason = ProjectStatus.ERROR, str(e)
            store.log_event(session, "ai_error", f"{project.title}: {e}", "error", project.id)
            await session.commit()
            return project.status

        proposal = await save_draft(session, project, draft, s)
        send_now = s.mode == "auto" or (s.mode == "semi" and result.score >= s.semi_auto_min_score)
        title, url, score, proposal_id = project.title, project.url, result.score, proposal.id

    if send_now:
        try:
            await send_proposal(sv, proposal_id, auto=True)
        except SendError as e:
            # The run moves on to the next project; this one stays in the queue as pending or failed.
            logger.info("Auto-send skipped for %s: %s", project_id, e)
    else:
        await sv.notifier.send(f"EasyBid: proposal waiting for approval (score {score})\n{title}\n{url}")
    return ProjectStatus.PROPOSED


async def release_stale_claims(session: AsyncSession) -> None:
    """Recover rows left mid-flight by a crashed or restarted process."""
    cutoff = utcnow() - STALE_CLAIM
    await session.execute(
        update(Project)
        .where(Project.status == ProjectStatus.PROCESSING, Project.updated_at < cutoff)
        .values(status=ProjectStatus.NEW)
    )
    await session.execute(
        update(Proposal)
        .where(Proposal.status == ProposalStatus.SENDING, Proposal.updated_at < cutoff)
        .values(status=ProposalStatus.FAILED, error="Interrupted while sending. Check Freelancer before retrying.")
    )
    await session.commit()


async def run_cycle(sv: Services) -> dict:
    """Fetch new projects and process them. Safe to call from several places at once."""
    if _cycle_lock.locked():
        return {"skipped": "a cycle is already running"}
    async with _cycle_lock:
        async with sv.sessions() as session:
            s = await store.get_settings(session)
            if s.paused:
                return {"skipped": "paused"}
            if not s.skill_ids:
                return {"skipped": "no skills selected in Settings"}
            ai_problem = sv.llm.problem(s)
            if ai_problem:
                return {"skipped": ai_problem}
            if await active_prompt(session, "proposal") is None:
                return {"skipped": "no active proposal prompt"}
            wait = await bidding_wait(session, s)
            if wait:
                return {"skipped": wait}

            # Fresh bids-left, balance and verification status before spending anything on AI.
            try:
                account = await get_account(sv, session, refresh=True)
            except FreelancerError as e:
                store.log_event(session, "fetch_failed", f"Account check: {e}", "error")
                await session.commit()
                return {"error": str(e)}
            blocked = eligibility.account_problem(account)
            if blocked:
                return {"skipped": blocked}

            await release_stale_claims(session)
            try:
                fetched = await fetch_new_projects(sv, session, s)
            except FreelancerError as e:
                store.log_event(session, "fetch_failed", str(e), "error")
                await session.commit()
                return {"error": str(e)}

            ids = list(
                await session.scalars(
                    select(Project.id)
                    .where(Project.status == ProjectStatus.NEW)
                    .order_by(Project.submitted_at.desc())
                    .limit(s.max_projects_per_cycle)
                )
            )

        summary: dict = {"fetched": fetched}
        for project_id in ids:
            # Once no bid can go out, the rest stay untouched: no proposal is written for nothing.
            async with sv.sessions() as session:
                if await bidding_wait(session, s):
                    break
            try:
                status = await process_project(sv, project_id)
            except Exception as e:  # one bad project must not stop the run
                logger.exception("Project %s failed", project_id)
                status = ProjectStatus.ERROR
                async with sv.sessions() as session:
                    await session.execute(
                        update(Project).where(Project.id == project_id).values(status=status, reason=repr(e)[:500])
                    )
                    await session.commit()
            summary[status] = summary.get(status, 0) + 1

        if fetched or ids:
            async with sv.sessions() as session:
                store.log_event(session, "cycle", ", ".join(f"{k}: {v}" for k, v in summary.items()))
                await session.commit()
        return summary


async def sync_bids(sv: Services) -> int:
    """Refresh the status of sent bids (awarded, rejected, retracted...). Returns how many changed."""
    changed = 0
    async with sv.sessions() as session:
        since = utcnow() - timedelta(days=30)
        proposals = list(
            await session.scalars(
                select(Proposal).where(
                    Proposal.status == ProposalStatus.SENT,
                    Proposal.freelancer_bid_id.is_not(None),
                    Proposal.sent_at >= since,
                )
            )
        )
        by_bid = {p.freelancer_bid_id: p for p in proposals}
        bid_ids = list(by_bid)
        for i in range(0, len(bid_ids), 50):
            try:
                bids = await sv.freelancer.get_bids(bid_ids[i : i + 50])
            except FreelancerError as e:
                store.log_event(session, "sync_failed", str(e), "error")
                break
            for bid in bids:
                proposal = by_bid.get(bid["id"])
                status = bid_status(bid)
                if proposal is None or proposal.bid_status == status:
                    continue
                proposal.bid_status = status
                changed += 1
                store.log_event(
                    session, "bid_status", f"{proposal.project.title}: {status}", "info", proposal.project_id
                )
                if status == "awarded":
                    await sv.notifier.send(
                        f"EasyBid: you were awarded \"{proposal.project.title}\"\n{proposal.project.url}"
                    )
        await session.commit()
    return changed


def _due(runtime: dict, key: str, interval: timedelta, now: datetime) -> bool:
    last = runtime.get(key)
    return last is None or now - datetime.fromisoformat(last) >= interval


def scheduler_running(runtime: dict) -> bool:
    """Whether the scheduler has ticked recently. False means nothing is being checked automatically."""
    return not _due(runtime, "last_tick", HEARTBEAT_STALE, utcnow())


async def tick(sv: Services, owner: str = "scheduler", standby: bool = False) -> None:
    """Called every few seconds by a scheduler; runs whatever is due.

    A standby scheduler does nothing while another one is alive, and takes over when that one goes quiet.
    """
    now = utcnow()
    async with sv.sessions() as session:
        s = await store.get_settings(session)
        runtime = await store.get_config(session, store.RUNTIME)
        if standby and runtime.get("tick_owner") != owner and scheduler_running(runtime):
            return
        run_now = not s.paused and _due(runtime, "last_cycle", timedelta(seconds=s.poll_interval_seconds), now)
        sync_now = _due(runtime, "last_sync", BID_SYNC_INTERVAL, now)
        beat = _due(runtime, "last_tick", HEARTBEAT, now)
        if run_now:
            runtime["last_cycle"] = now.isoformat()
        if sync_now:
            runtime["last_sync"] = now.isoformat()
        if beat:
            runtime["last_tick"], runtime["tick_owner"] = now.isoformat(), owner
        if run_now or sync_now or beat:
            await store.set_config(session, store.RUNTIME, runtime)
            await session.commit()

    if run_now:
        await run_cycle(sv)
    if sync_now:
        await sync_bids(sv)
