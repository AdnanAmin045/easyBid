import asyncio
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import Text, cast, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import schemas
from app.db import get_session
from app.pagination import Page, PageParams, contains, paginate
from app.models import EventLog, ProfileItem, Project, ProjectStatus, Prompt, Proposal, ProposalStatus, utcnow
from app.security import check_credentials, create_token, require_user
from app.services import eligibility, pipeline, store
from app.services.freelancer import FreelancerError
from app.services.llm import LLMError, clean_proposal
from app.services.pipeline import SendError, Services

public = APIRouter(prefix="/api")
router = APIRouter(prefix="/api", dependencies=[Depends(require_user)])


def services(request: Request) -> Services:
    return request.app.state.services


# --- auth ---------------------------------------------------------------


@public.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@public.post("/auth/login", response_model=schemas.TokenOut)
async def login(body: schemas.LoginIn):
    if not check_credentials(body.email, body.password):
        # Slow down password guessing.
        await asyncio.sleep(1)
        raise HTTPException(401, "Wrong email or password")
    return {"token": create_token()}


# --- overview -----------------------------------------------------------


@router.get("/stats")
async def stats(session: AsyncSession = Depends(get_session), sv: Services = Depends(services)) -> dict:
    s = await store.get_settings(session)
    runtime = await store.get_config(session, store.RUNTIME)
    try:
        # Kept fresh here too, so the dashboard is right even while EasyBid is paused.
        account = await pipeline.get_account(sv, session, max_age=timedelta(minutes=5))
    except FreelancerError:
        account = await store.get_config(session, store.ACCOUNT)
    day_ago = utcnow() - timedelta(hours=24)

    project_rows = await session.execute(
        select(Project.status, func.count()).where(Project.created_at >= day_ago).group_by(Project.status)
    )
    proposal_rows = await session.execute(select(Proposal.status, func.count()).group_by(Proposal.status))
    proposals = dict(proposal_rows.all())

    prompt_rows = await session.execute(
        select(Prompt.id, Prompt.version, Prompt.is_active, Proposal.bid_status, func.count())
        .join(Proposal, Proposal.prompt_id == Prompt.id)
        .where(Proposal.status == ProposalStatus.SENT)
        .group_by(Prompt.id, Prompt.version, Prompt.is_active, Proposal.bid_status)
    )
    by_prompt: dict[int, dict] = {}
    for prompt_id, version, is_active, status, count in prompt_rows:
        row = by_prompt.setdefault(prompt_id, {"version": version, "is_active": is_active, "sent": 0, "awarded": 0})
        row["sent"] += count
        if status == "awarded":
            row["awarded"] += count

    return {
        "paused": s.paused,
        "mode": s.mode,
        "skills_selected": len(s.skill_ids),
        "ai_problem": sv.llm.problem(s),
        "proposal_prompt_active": await pipeline.active_prompt(session, "proposal") is not None,
        "last_cycle": runtime.get("last_cycle"),
        "account": {k: v for k, v in account.items() if k != "skills"},
        "account_problem": eligibility.account_problem(account) if account else None,
        "waiting": await pipeline.bidding_wait(session, s),
        "scheduler_running": pipeline.scheduler_running(runtime),
        "projects_24h": dict(project_rows.all()),
        "proposals": proposals,
        "sent_today": await pipeline.bids_sent_today(session),
        "daily_bid_cap": s.daily_bid_cap,
        "awarded": sum(r["awarded"] for r in by_prompt.values()),
        "prompts": sorted(by_prompt.values(), key=lambda r: -r["version"]),
    }


@router.post("/run")
async def run_now(sv: Services = Depends(services)) -> dict:
    return await pipeline.run_cycle(sv)


@router.get("/logs", response_model=Page[schemas.LogOut])
async def logs(
    level: Literal["info", "error"] | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    query = select(EventLog).order_by(EventLog.id.desc())
    if level:
        query = query.where(EventLog.level == level)
    if params.q:
        query = query.where(contains(params.q, EventLog.message, EventLog.event))
    return await paginate(session, query, params)


# --- settings and account -----------------------------------------------


@router.get("/settings", response_model=schemas.AppSettings)
async def read_settings(session: AsyncSession = Depends(get_session)):
    return await store.get_settings(session)


@router.put("/settings", response_model=schemas.AppSettings)
async def write_settings(body: schemas.AppSettings, session: AsyncSession = Depends(get_session)):
    if body.proposal_min_chars > body.proposal_max_chars:
        raise HTTPException(422, "Proposal minimum length is above the maximum")
    await store.save_settings(session, body)
    store.log_event(session, "settings", f"Settings saved (mode {body.mode}, paused {body.paused})")
    await session.commit()
    return body


@router.get("/account")
async def account(
    refresh: bool = False, session: AsyncSession = Depends(get_session), sv: Services = Depends(services)
) -> dict:
    try:
        return await pipeline.get_account(sv, session, refresh=refresh)
    except FreelancerError as e:
        raise HTTPException(502, f"Freelancer: {e}") from e


@router.get("/skills", response_model=list[schemas.SkillOut])
async def skills(request: Request, q: str = "", sv: Services = Depends(services)):
    cache = request.app.state.skill_cache
    if not cache:
        try:
            cache.extend(await sv.freelancer.list_skills())
        except FreelancerError as e:
            raise HTTPException(502, f"Freelancer: {e}") from e
    needle = q.strip().lower()
    return [k for k in cache if needle in k["name"].lower()][:50]


# --- projects -----------------------------------------------------------


@router.get("/projects", response_model=Page[schemas.ProjectOut])
async def list_projects(
    status: str | None = None,
    type: Literal["fixed", "hourly"] | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    """Newest first. `q` searches the title, description, skill tags and the reason it was taken or left."""
    query = select(Project).order_by(Project.created_at.desc(), Project.id.desc())
    if status:
        query = query.where(Project.status == status)
    if type:
        query = query.where(Project.type == type)
    if params.q:
        query = query.where(contains(params.q, Project.title, Project.description, cast(Project.skills, Text), Project.reason))
    return await paginate(session, query, params)


@router.post("/projects/{project_id}/generate", response_model=schemas.ProposalOut)
async def generate_proposal(
    project_id: int, session: AsyncSession = Depends(get_session), sv: Services = Depends(services)
):
    """Write (or rewrite) a proposal for any project, including filtered and skipped ones."""
    project = await session.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    s = await store.get_settings(session)
    try:
        draft = await pipeline.write_draft(sv, session, project, s)
        return await pipeline.save_draft(session, project, draft, s)
    except (LLMError, SendError) as e:
        raise HTTPException(409, str(e)) from e


# --- proposals ----------------------------------------------------------


@router.get("/proposals", response_model=Page[schemas.ProposalWithProject])
async def list_proposals(
    status: str | None = Query(None, description="One or more proposal statuses, comma-separated"),
    bid_status: str | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    """Most recently changed first. `q` searches the project title and the proposal text."""
    query = select(Proposal).join(Proposal.project).order_by(Proposal.updated_at.desc(), Proposal.id.desc())
    if status:
        query = query.where(Proposal.status.in_(status.split(",")))
    if bid_status:
        query = query.where(Proposal.bid_status == bid_status)
    if params.q:
        query = query.where(contains(params.q, Project.title, Proposal.text))
    return await paginate(session, query, params)


async def _editable(session: AsyncSession, proposal_id: int) -> Proposal:
    proposal = await session.get(Proposal, proposal_id)
    if proposal is None:
        raise HTTPException(404, "Proposal not found")
    if proposal.status in (ProposalStatus.SENT, ProposalStatus.SENDING):
        raise HTTPException(409, "This bid was already sent")
    return proposal


@router.patch("/proposals/{proposal_id}", response_model=schemas.ProposalOut)
async def edit_proposal(proposal_id: int, body: schemas.ProposalUpdate, session: AsyncSession = Depends(get_session)):
    proposal = await _editable(session, proposal_id)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(proposal, field, clean_proposal(value) if field == "text" else value)
    await session.commit()
    return proposal


@router.post("/proposals/{proposal_id}/approve", response_model=schemas.ProposalOut)
async def approve_proposal(proposal_id: int, sv: Services = Depends(services)):
    try:
        return await pipeline.send_proposal(sv, proposal_id)
    except SendError as e:
        raise HTTPException(409, str(e)) from e


@router.post("/proposals/{proposal_id}/reject", response_model=schemas.ProposalOut)
async def reject_proposal(proposal_id: int, session: AsyncSession = Depends(get_session)):
    proposal = await _editable(session, proposal_id)
    proposal.status = ProposalStatus.REJECTED
    await session.commit()
    return proposal


# --- prompts ------------------------------------------------------------


@router.get("/prompts", response_model=Page[schemas.PromptOut])
async def list_prompts(
    kind: schemas.PromptKind | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    """Saved versions, newest first. `q` searches the prompt text and its note."""
    query = select(Prompt).order_by(Prompt.kind, Prompt.version.desc())
    if kind:
        query = query.where(Prompt.kind == kind)
    if params.q:
        query = query.where(contains(params.q, Prompt.content, Prompt.note))
    return await paginate(session, query, params)


@router.get("/prompts/current", response_model=schemas.PromptOut | None)
async def current_prompt(kind: schemas.PromptKind, session: AsyncSession = Depends(get_session)):
    """The active version of a prompt, or the newest one if none is active."""
    active = await pipeline.active_prompt(session, kind)
    if active:
        return active
    return await session.scalar(select(Prompt).where(Prompt.kind == kind).order_by(Prompt.version.desc()).limit(1))


async def _activate(session: AsyncSession, prompt: Prompt) -> None:
    await session.execute(update(Prompt).where(Prompt.kind == prompt.kind).values(is_active=False))
    prompt.is_active = True


@router.post("/prompts", response_model=schemas.PromptOut)
async def create_prompt(body: schemas.PromptIn, session: AsyncSession = Depends(get_session)):
    """Every save is a new version; old versions are kept."""
    latest = await session.scalar(select(func.max(Prompt.version)).where(Prompt.kind == body.kind))
    prompt = Prompt(kind=body.kind, version=(latest or 0) + 1, content=body.content, note=body.note)
    session.add(prompt)
    if body.activate:
        await _activate(session, prompt)
    await session.commit()
    return prompt


@router.post("/prompts/{prompt_id}/activate", response_model=schemas.PromptOut)
async def activate_prompt(prompt_id: int, active: bool = True, session: AsyncSession = Depends(get_session)):
    prompt = await session.get(Prompt, prompt_id)
    if prompt is None:
        raise HTTPException(404, "Prompt not found")
    if active:
        await _activate(session, prompt)
    else:
        prompt.is_active = False
    await session.commit()
    return prompt


@router.post("/prompts/test", response_model=schemas.PromptTestOut)
async def test_prompt(
    body: schemas.PromptTestIn, session: AsyncSession = Depends(get_session), sv: Services = Depends(services)
):
    """Preview a prompt against a real project. Nothing is saved and no bid is sent."""
    project = await session.get(Project, body.project_id)
    if project is None:
        raise HTTPException(404, "Project not found")
    s = await store.get_settings(session)
    try:
        if body.kind == "selection":
            decision = await sv.llm.select(body.content, project, await pipeline.active_profile(session), s)
            return {"apply": decision.apply, "reason": decision.reason}
        draft = await pipeline.write_draft(sv, session, project, s, prompt_content=body.content)
        return {"text": draft.text, "chars": len(draft.text), "amount": draft.amount, "period": draft.period}
    except LLMError as e:
        raise HTTPException(409, str(e)) from e


# --- profile ------------------------------------------------------------


@router.get("/profile", response_model=Page[schemas.ProfileItemOut])
async def list_profile(
    kind: Literal["bio", "skill", "project", "link"] | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    query = select(ProfileItem).order_by(ProfileItem.kind, ProfileItem.id)
    if kind:
        query = query.where(ProfileItem.kind == kind)
    if params.q:
        query = query.where(contains(params.q, ProfileItem.title, ProfileItem.content))
    return await paginate(session, query, params)


@router.post("/profile", response_model=schemas.ProfileItemOut)
async def create_profile_item(body: schemas.ProfileItemIn, session: AsyncSession = Depends(get_session)):
    item = ProfileItem(**body.model_dump())
    session.add(item)
    await session.commit()
    return item


@router.put("/profile/{item_id}", response_model=schemas.ProfileItemOut)
async def update_profile_item(item_id: int, body: schemas.ProfileItemIn, session: AsyncSession = Depends(get_session)):
    item = await session.get(ProfileItem, item_id)
    if item is None:
        raise HTTPException(404, "Profile item not found")
    for field, value in body.model_dump().items():
        setattr(item, field, value)
    await session.commit()
    return item


@router.delete("/profile/{item_id}", status_code=204)
async def delete_profile_item(item_id: int, session: AsyncSession = Depends(get_session)):
    item = await session.get(ProfileItem, item_id)
    if item is None:
        raise HTTPException(404, "Profile item not found")
    await session.delete(item)
    await session.commit()
