"""HTTP API of the LinkedIn service, under /api/linkedin."""

import io
from datetime import timedelta
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_env
from app.db import get_session
from app.jobs import gmail as crypto
from app.linkedin import content, engine, prompts, research, site
from app.linkedin import client as li
from app.linkedin.client import LinkedInError, post_url
from app.linkedin.engine import LinkedInServices
from app.linkedin.models import COMPANY, PERSONAL, LinkedInAccount, LinkedInCache, LinkedInPost, PostStatus
from app.linkedin.poster import render_poster
from app.linkedin.schemas import (
    AccountOut,
    ApproveIn,
    GenerateIn,
    Idea,
    IdeasIn,
    LinkedInSettings,
    PosterSpec,
    timing_problems,
    PostOut,
    PostPatch,
)
from app.models import utcnow
from app.security import require_user
from app.services import store
from app.services.llm import LLMError

public = APIRouter(prefix="/api/linkedin")
# The redirect URL some people register in the LinkedIn app has no /api in front of it.
alias = APIRouter()
router = APIRouter(prefix="/api/linkedin", dependencies=[Depends(require_user)])

EDITABLE = (PostStatus.DRAFT, PostStatus.APPROVED, PostStatus.FAILED)
MAX_LOGO_BYTES = 3 * 1024 * 1024


def services(request: Request) -> LinkedInServices:
    return request.app.state.linkedin


def out(post: LinkedInPost) -> PostOut:
    return PostOut(
        id=post.id, target=post.target, post_date=post.post_date, slot=post.slot, pillar=post.pillar, topic=post.topic, text=post.text,
        first_comment=post.first_comment, poster_spec=post.poster_spec, has_poster=post.poster is not None, alt_text=post.alt_text,
        signals=post.signals or {}, status=post.status, scheduled_for=post.scheduled_for, posted_at=post.posted_at, linkedin_urn=post.linkedin_urn,
        linkedin_url=post_url(post.linkedin_urn), error=post.error, created_at=post.created_at,
    )


async def _post(session: AsyncSession, post_id: int) -> LinkedInPost:
    post = await session.get(LinkedInPost, post_id)
    if post is None:
        raise HTTPException(404, "Post not found")
    return post


def _account_out(target: str, account: LinkedInAccount | None, s: LinkedInSettings, svc: LinkedInServices) -> AccountOut:
    configured = svc.client.configured(target)
    problem = ""
    if not configured:
        problem = (
            "LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET are not set on the server"
            if target == PERSONAL
            else "LINKEDIN_ORG_CLIENT_ID and LINKEDIN_ORG_CLIENT_SECRET are not set on the server. The company page needs its own LinkedIn "
            "developer app with the Community Management API."
        )
    elif target == COMPANY and not s.company_page_id:
        problem = "Add the company page id in the settings first."
    elif account and not engine.usable(account):
        problem = "The LinkedIn login has expired. Connect again."
    left = (account.expires_at - utcnow()).days if account and account.expires_at else None
    return AccountOut(
        target=target, configured=configured, connected=engine.usable(account), name=account.name if account else "",
        author_urn=engine.author_for(target, account, s), expires_at=account.expires_at if account else None, days_left=left, problem=problem,
    )


# --- overview and settings ------------------------------------------------------------


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services)) -> dict:
    s, _ = await engine.get_config(session)
    await session.commit()
    accounts = {a.target: a for a in await session.scalars(select(LinkedInAccount))}
    by_target: dict[str, dict[str, int]] = {PERSONAL: {}, COMPANY: {}}
    for target, status, n in (await session.execute(select(LinkedInPost.target, LinkedInPost.status, func.count()).group_by(LinkedInPost.target, LinkedInPost.status))).all():
        by_target.setdefault(target, {})[status] = n
    today = engine.local_now(s).date()
    todays = {t: await session.scalar(select(func.count()).select_from(LinkedInPost).where(LinkedInPost.target == t, LinkedInPost.post_date == today)) or 0 for t in (PERSONAL, COMPANY)}
    return {
        "accounts": [_account_out(t, accounts.get(t), s, svc).model_dump(mode="json") for t in (PERSONAL, COMPANY)],
        "counts": by_target,
        "today": todays,
        "redirect_uri": svc.client.redirect_uri,
        "settings": s.model_dump(),
        "now_local": engine.local_now(s).isoformat(timespec="minutes"),
        "warnings": timing_problems(s),
    }


@router.put("/settings", response_model=LinkedInSettings)
async def write_settings(body: LinkedInSettings, session: AsyncSession = Depends(get_session)):
    errors = [p["message"] for p in timing_problems(body) if p["level"] == "error"]
    if errors:
        raise HTTPException(422, " ".join(errors))
    _, row = await engine.get_config(session)
    row.data = body.model_dump()
    store.log_event(session, "linkedin_settings", "LinkedIn settings saved")
    await session.commit()
    return body


@router.get("/settings/defaults")
async def settings_defaults() -> dict:
    """The recommended settings, and the built-in text of every instruction the planner and the writer follow."""
    return {
        "settings": LinkedInSettings().model_dump(),
        "prompts": {
            "writer_style": prompts.DEFAULT_WRITER_STYLE,
            "planner_guidance": prompts.DEFAULT_PLANNER_GUIDANCE,
            "poster_guidance": prompts.DEFAULT_POSTER_GUIDANCE,
            "pillars": prompts.pillar_defaults(),
            "locked_rules": prompts.LOCKED_RULES,
        },
    }


@router.get("/research")
async def get_research(session: AsyncSession = Depends(get_session)) -> dict:
    """What was found out about the field today, as last saved. Empty until the first post of the day is written."""
    s, _ = await engine.get_config(session)
    row = await session.get(LinkedInCache, f"research:{engine.local_now(s).date().isoformat()}")
    await session.commit()
    return {"found": bool(row), **(row.data if row else {}), "fetched_at": row.fetched_at if row else None}


@router.post("/research/refresh")
async def refresh_research(session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services)) -> dict:
    """Search the web again for today's news in the field."""
    s, _ = await engine.get_config(session)
    try:
        found = await research.get_research(svc.llm, session, s, engine.local_now(s).date(), force=True)
    except LLMError as e:
        raise HTTPException(503, str(e)) from e
    await session.commit()
    return {"found": True, **found.as_dict()}


@router.get("/site")
async def get_site(session: AsyncSession = Depends(get_session)) -> dict:
    """The website text the company posts are allowed to rely on, as last read."""
    row = await session.get(LinkedInCache, site.KEY)
    return {"url": row.data.get("url", "") if row else "", "text": row.data.get("text", "") if row else "", "fetched_at": row.fetched_at if row else None}


@router.post("/site/refresh")
async def refresh_site(session: AsyncSession = Depends(get_session)) -> dict:
    """Read the company website again."""
    s, _ = await engine.get_config(session)
    result = await site.get_site(session, s.website_url, force=True)
    if not result["text"]:
        raise HTTPException(502, f"Could not read {s.website_url or 'a website'}. Check the address in the settings.")
    await session.commit()
    return result


@router.post("/ideas", response_model=list[Idea])
async def ideas(body: IdeasIn, session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services)):
    """Topic ideas for today, from this week's research and what this profile can speak about. Pick one to write."""
    s, _ = await engine.get_config(session)
    try:
        found = await content.suggest_ideas(svc.llm, session, body.target, s, engine.local_now(s).date(), body.count)
    except LLMError as e:
        raise HTTPException(503, f"The planner is unavailable: {e}") from e
    await session.commit()
    return found


# --- connecting accounts --------------------------------------------------------------


@router.post("/connect/{target}")
async def connect(target: str, svc: LinkedInServices = Depends(services), session: AsyncSession = Depends(get_session)) -> dict:
    if target not in (PERSONAL, COMPANY):
        raise HTTPException(404, "Unknown account")
    if not svc.client.configured(target):
        raise HTTPException(409, _account_out(target, None, LinkedInSettings(), svc).problem)
    s, _ = await engine.get_config(session)
    if target == COMPANY and not s.company_page_id:
        raise HTTPException(409, "Add the company page id in the settings first.")
    return {"url": svc.client.auth_url(target, li.make_state(get_env().secret_key, target))}


async def _callback(state: str, code: str, error: str, error_description: str, session: AsyncSession, svc: LinkedInServices) -> RedirectResponse:
    env = get_env()

    def back(result: str, message: str = "") -> RedirectResponse:
        return RedirectResponse(f"{env.dashboard_url}/linkedin?connect={result}" + (f"&message={quote(message)}" if message else ""), status_code=303)

    target = li.check_state(state, env.secret_key)
    if target is None:
        return back("error", "The connection request expired or did not come from this app. Try again.")
    if error or not code:
        return back("error", error_description or error or "LinkedIn did not return an authorisation code")
    try:
        tokens = await svc.client.exchange_code(target, code)
        token = tokens["access_token"]
        s, _ = await engine.get_config(session)
        if target == PERSONAL:
            urn, name = await svc.client.member(token)
        else:
            if not s.company_page_id:
                return back("error", "Add the company page id in the settings first.")
            urn, name = f"urn:li:organization:{s.company_page_id}", s.brand_name
    except (LinkedInError, KeyError) as e:
        return back("error", str(e))
    account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == target))
    if account is None:
        account = LinkedInAccount(target=target)
        session.add(account)
    account.name, account.author_urn = name, urn
    account.access_token = crypto.encrypt(token, env.secret_key)
    account.expires_at = utcnow() + timedelta(seconds=int(tokens.get("expires_in", 5184000)))
    account.scopes, account.expiry_warned, account.connected_at = tokens.get("scope", ""), False, utcnow()
    store.log_event(session, "linkedin_connect", f"LinkedIn connected: {target} ({name})")
    await session.commit()
    return back("connected", target)


@public.get("/callback", include_in_schema=False)
async def callback(
    state: str = "", code: str = "", error: str = "", error_description: str = "",
    session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services),
):
    return await _callback(state, code, error, error_description, session, svc)


@alias.get("/linkedin/callback", include_in_schema=False)
async def callback_alias(
    state: str = "", code: str = "", error: str = "", error_description: str = "",
    session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services),
):
    return await _callback(state, code, error, error_description, session, svc)


@router.delete("/accounts/{target}", status_code=204)
async def disconnect(target: str, session: AsyncSession = Depends(get_session)):
    account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == target))
    if account:
        await session.delete(account)
        store.log_event(session, "linkedin_connect", f"LinkedIn disconnected: {target}")
        await session.commit()


# --- logo -----------------------------------------------------------------------------


@router.post("/logo", status_code=204)
async def upload_logo(file: UploadFile = File(...), session: AsyncSession = Depends(get_session)):
    data = await file.read(MAX_LOGO_BYTES + 1)
    if len(data) > MAX_LOGO_BYTES:
        raise HTTPException(413, "The logo is larger than 3 MB")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "Upload a PNG, JPG or WebP image") from None
    img = img.convert("RGBA")
    img.thumbnail((900, 300))
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    _, row = await engine.get_config(session)
    row.logo, row.logo_type = buf.getvalue(), "image/png"
    await session.commit()


@router.get("/logo")
async def get_logo(session: AsyncSession = Depends(get_session)) -> Response:
    _, row = await engine.get_config(session)
    await session.commit()
    logo = row.logo or (engine.DEFAULT_LOGO.read_bytes() if engine.DEFAULT_LOGO.exists() else None)
    if not logo:
        raise HTTPException(404, "No logo uploaded")
    return Response(logo, media_type=row.logo_type or "image/png")


@router.delete("/logo", status_code=204)
async def delete_logo(session: AsyncSession = Depends(get_session)):
    _, row = await engine.get_config(session)
    row.logo, row.logo_type = None, ""
    await session.commit()


@router.post("/poster-preview")
async def poster_preview(spec: PosterSpec, target: str = COMPANY, session: AsyncSession = Depends(get_session)) -> Response:
    s, row = await engine.get_config(session)
    brand = await engine.brand_for(session, target, s, row)
    await session.commit()
    return Response(render_poster(spec.model_dump(), brand), media_type="image/png")


# --- posts ----------------------------------------------------------------------------


@router.get("/posts", response_model=list[PostOut])
async def list_posts(target: str = "", status: str = "", limit: int = 60, session: AsyncSession = Depends(get_session)):
    query = select(LinkedInPost).order_by(LinkedInPost.post_date.desc(), LinkedInPost.id.desc()).limit(min(max(limit, 1), 200))
    if target:
        query = query.where(LinkedInPost.target == target)
    if status:
        query = query.where(LinkedInPost.status.in_(status.split(",")))
    return [out(p) for p in await session.scalars(query)]


@router.get("/posts/{post_id}", response_model=PostOut)
async def get_post(post_id: int, session: AsyncSession = Depends(get_session)):
    return out(await _post(session, post_id))


@router.get("/posts/{post_id}/poster.png")
async def get_poster(post_id: int, session: AsyncSession = Depends(get_session)) -> Response:
    post = await _post(session, post_id)
    if not post.poster:
        raise HTTPException(404, "This post has no poster")
    return Response(post.poster, media_type="image/png")


@router.post("/posts/generate", response_model=PostOut)
async def generate(body: GenerateIn, session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services)):
    """Write another post now, for today, on a topic you give or one the writer picks."""
    s, row = await engine.get_config(session)
    day = engine.local_now(s).date()
    try:
        post = await engine.create_draft(svc, session, body.target, day, s, row, brief=body.brief)
    except LLMError as e:
        raise HTTPException(503, f"The writer is unavailable: {e}") from e
    await session.commit()
    return out(post)


@router.patch("/posts/{post_id}", response_model=PostOut)
async def update_post(post_id: int, body: PostPatch, session: AsyncSession = Depends(get_session)):
    post = await _post(session, post_id)
    if post.status not in EDITABLE:
        raise HTTPException(409, "A post that has gone out or been rejected cannot be edited")
    fields = body.model_fields_set
    if body.text is not None:
        post.text = body.text.strip()
    for name in ("first_comment", "topic", "alt_text"):
        if getattr(body, name) is not None:
            setattr(post, name, getattr(body, name))
    if "scheduled_for" in fields and body.scheduled_for:
        post.scheduled_for = body.scheduled_for
    if body.remove_poster:
        post.poster, post.poster_spec, post.alt_text = None, None, ""
    elif body.poster_spec is not None:
        s, row = await engine.get_config(session)
        post.poster_spec = body.poster_spec.model_dump()
        post.poster = render_poster(post.poster_spec, await engine.brand_for(session, post.target, s, row))
    if post.status == PostStatus.FAILED:
        post.status, post.error = PostStatus.DRAFT, ""
    await session.commit()
    return out(post)


@router.post("/posts/{post_id}/render", response_model=PostOut)
async def rerender(post_id: int, session: AsyncSession = Depends(get_session)):
    """Draw the poster again, for example after the logo or colours changed."""
    post = await _post(session, post_id)
    if post.status not in EDITABLE or not post.poster_spec:
        raise HTTPException(409, "This post has no poster that can be redrawn")
    s, row = await engine.get_config(session)
    post.poster = render_poster(post.poster_spec, await engine.brand_for(session, post.target, s, row))
    await session.commit()
    return out(post)


@router.post("/posts/{post_id}/rewrite", response_model=PostOut)
async def rewrite(post_id: int, body: GenerateIn, session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services)):
    """Write this post again from scratch, optionally on a topic you give."""
    post = await _post(session, post_id)
    if post.status not in EDITABLE:
        raise HTTPException(409, "A post that has gone out or been rejected cannot be rewritten")
    s, row = await engine.get_config(session)
    try:
        brand = await engine.brand_for(session, post.target, s, row)
        made = await content.generate_post(svc.llm, session, post.target, s, post.post_date, body.brief, brand)
    except LLMError as e:
        raise HTTPException(503, f"The writer is unavailable: {e}") from e
    post.topic, post.pillar, post.text, post.poster_spec, post.alt_text, post.signals = made.topic, made.pillar, made.text, made.poster_spec, made.alt_text, made.signals
    post.poster = render_poster(made.poster_spec, brand) if made.poster_spec else None
    post.status, post.error = PostStatus.DRAFT, ""
    await session.commit()
    return out(post)


async def _ready_to_post(session: AsyncSession, post: LinkedInPost) -> None:
    s, _ = await engine.get_config(session)
    account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == post.target))
    if not engine.usable(account):
        raise HTTPException(409, "This profile is not connected to LinkedIn. Connect it first, or copy the post and publish it yourself.")
    if not engine.author_for(post.target, account, s):
        raise HTTPException(409, "Add the company page id in the settings first.")


@router.post("/posts/{post_id}/approve", response_model=PostOut)
async def approve(post_id: int, body: ApproveIn, session: AsyncSession = Depends(get_session)):
    post = await _post(session, post_id)
    if post.status not in (PostStatus.DRAFT, PostStatus.FAILED):
        raise HTTPException(409, "Only a draft can be approved")
    await _ready_to_post(session, post)
    when = body.scheduled_for or post.scheduled_for or utcnow()
    post.scheduled_for = max(when, utcnow()) if when < utcnow() else when
    post.status, post.error = PostStatus.APPROVED, ""
    await session.commit()
    return out(post)


@router.post("/posts/{post_id}/unapprove", response_model=PostOut)
async def unapprove(post_id: int, session: AsyncSession = Depends(get_session)):
    post = await _post(session, post_id)
    if post.status != PostStatus.APPROVED:
        raise HTTPException(409, "Only an approved post can go back to draft")
    post.status = PostStatus.DRAFT
    await session.commit()
    return out(post)


@router.post("/posts/{post_id}/post-now", response_model=PostOut)
async def post_now(post_id: int, session: AsyncSession = Depends(get_session), svc: LinkedInServices = Depends(services)):
    post = await _post(session, post_id)
    if post.status not in (PostStatus.DRAFT, PostStatus.APPROVED, PostStatus.FAILED):
        raise HTTPException(409, "This post cannot be posted")
    await _ready_to_post(session, post)
    post.status, post.error, post.scheduled_for = PostStatus.APPROVED, "", utcnow()
    await session.commit()
    try:
        done = await engine.publish(svc, post_id)
    except LinkedInError as e:
        raise HTTPException(409, str(e)) from e
    return out(done)


@router.post("/posts/{post_id}/reject", response_model=PostOut)
async def reject(post_id: int, session: AsyncSession = Depends(get_session)):
    post = await _post(session, post_id)
    if post.status not in EDITABLE:
        raise HTTPException(409, "This post cannot be rejected")
    post.status = PostStatus.REJECTED
    await session.commit()
    return out(post)


@router.post("/posts/{post_id}/mark-posted", response_model=PostOut)
async def mark_posted(post_id: int, session: AsyncSession = Depends(get_session)):
    """For a post you published by hand, for example on the company page before the API is approved."""
    post = await _post(session, post_id)
    if post.status not in EDITABLE:
        raise HTTPException(409, "This post cannot be marked as posted")
    post.status, post.posted_at, post.error = PostStatus.POSTED, utcnow(), ""
    await session.commit()
    return out(post)
