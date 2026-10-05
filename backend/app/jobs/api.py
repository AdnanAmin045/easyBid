"""HTTP API of the Jobs service, under /api/jobs."""

from dataclasses import dataclass
from datetime import timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_env
from app.db import get_session
from app.jobs import extract as extraction
from app.jobs import gmail as gmail_lib
from app.jobs import schemas
from app.jobs.gmail import Attachment, GmailClient, GmailError
from app.jobs.models import ApplicationStatus, JobApplication, JobProfileItem, JobPrompt, JobResume
from app.jobs.writer import DEFAULT_PROMPT, email_problem, write_email
from app.models import utcnow
from app.pagination import Page, PageParams, contains, paginate
from app.security import require_user
from app.services import store
from app.services.llm import LLM, LLMError

SETTINGS_KEY = "jobs_settings"
GMAIL_KEY = "jobs_gmail"
MAX_RESUME_BYTES = 5 * 1024 * 1024
RESUME_TYPES = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}

public = APIRouter(prefix="/api/jobs")
router = APIRouter(prefix="/api/jobs", dependencies=[Depends(require_user)])


@dataclass
class JobServices:
    sessions: async_sessionmaker[AsyncSession]
    llm: LLM
    gmail: GmailClient
    lookup: extraction.MailServerLookup = extraction.has_mail_server


def job_services(request: Request) -> JobServices:
    return request.app.state.jobs


async def get_settings(session: AsyncSession) -> schemas.JobSettings:
    return schemas.JobSettings(**await store.get_config(session, SETTINGS_KEY))


async def active_prompt(session: AsyncSession) -> JobPrompt | None:
    return await session.scalar(select(JobPrompt).where(JobPrompt.kind == "application", JobPrompt.is_active))


async def active_profile(session: AsyncSession) -> list[JobProfileItem]:
    return list(await session.scalars(select(JobProfileItem).where(JobProfileItem.is_active).order_by(JobProfileItem.id)))


async def sent_today(session: AsyncSession) -> int:
    midnight = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    query = select(func.count()).where(JobApplication.status == ApplicationStatus.SENT, JobApplication.sent_at >= midnight)
    return await session.scalar(query) or 0


async def previous_application(
    session: AsyncSession, email: str, company: str, days: int, exclude_id: int | None = None
) -> JobApplication | None:
    """The latest application sent to this address, or to this company, within `days`."""
    if days <= 0:
        return None
    conditions = [func.lower(JobApplication.to_email) == email.lower()]
    if company.strip():
        conditions.append(func.lower(JobApplication.company) == company.strip().lower())
    query = (
        select(JobApplication)
        .where(
            JobApplication.status == ApplicationStatus.SENT,
            JobApplication.sent_at >= utcnow() - timedelta(days=days),
            or_(*conditions),
        )
        .order_by(JobApplication.sent_at.desc())
        .limit(1)
    )
    if exclude_id is not None:
        query = query.where(JobApplication.id != exclude_id)
    return await session.scalar(query)


def _log(session: AsyncSession, event: str, message: str, level: str = "info") -> None:
    store.log_event(session, f"jobs_{event}", message, level)


# --- overview -------------------------------------------------------------------


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)) -> dict:
    s = await get_settings(session)
    account = await store.get_config(session, GMAIL_KEY)
    counts = dict((await session.execute(select(JobApplication.status, func.count()).group_by(JobApplication.status))).all())
    recent = await session.scalars(select(JobApplication).order_by(JobApplication.created_at.desc()).limit(5))
    return {
        "gmail": {"configured": js.gmail.configured, "connected": bool(account), "email": account.get("email")},
        "ai_problem": js.llm.model_problem(s.model),
        "prompt_active": await active_prompt(session) is not None,
        "profile_items": await session.scalar(select(func.count()).select_from(JobProfileItem)) or 0,
        "resumes": await session.scalar(select(func.count()).select_from(JobResume)) or 0,
        "sent_today": await sent_today(session),
        "daily_send_limit": s.daily_send_limit,
        "counts": counts,
        "recent": [schemas.ApplicationBrief.model_validate(a) for a in recent],
    }


# --- settings -------------------------------------------------------------------


@router.get("/settings", response_model=schemas.JobSettings)
async def read_settings(session: AsyncSession = Depends(get_session)):
    return await get_settings(session)


@router.put("/settings", response_model=schemas.JobSettings)
async def write_settings(body: schemas.JobSettings, session: AsyncSession = Depends(get_session)):
    await store.set_config(session, SETTINGS_KEY, body.model_dump())
    _log(session, "settings", "Jobs settings saved")
    await session.commit()
    return body


# --- gmail ----------------------------------------------------------------------


@router.get("/gmail", response_model=schemas.GmailStatus)
async def gmail_status(session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)):
    account = await store.get_config(session, GMAIL_KEY)
    return schemas.GmailStatus(
        configured=js.gmail.configured,
        connected=bool(account),
        email=account.get("email"),
        connected_at=account.get("connected_at"),
    )


@router.post("/gmail/connect")
async def gmail_connect(js: JobServices = Depends(job_services)) -> dict:
    if not js.gmail.configured:
        raise HTTPException(409, "Gmail is not set up on the server: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI are needed")
    return {"url": js.gmail.auth_url(gmail_lib.make_state(get_env().secret_key))}


@public.get("/gmail/callback", include_in_schema=False)
async def gmail_callback(
    state: str = "",
    code: str = "",
    error: str = "",
    session: AsyncSession = Depends(get_session),
    js: JobServices = Depends(job_services),
):
    """Google redirects the browser here after the consent screen; the result goes back to the dashboard."""
    env = get_env()

    def back(result: str, message: str = "") -> RedirectResponse:
        target = f"{env.dashboard_url}/jobs/settings?gmail={result}"
        return RedirectResponse(target + (f"&message={quote(message)}" if message else ""), status_code=303)

    if not gmail_lib.check_state(state, env.secret_key):
        return back("error", "The connection request expired or did not come from this app. Try again.")
    if error or not code:
        return back("error", error or "Google did not return an authorisation code")
    try:
        tokens = await js.gmail.exchange_code(code)
        email = await js.gmail.profile_email(tokens["access_token"])
    except GmailError as e:
        return back("error", str(e))

    account = {
        "email": email,
        "refresh_token": gmail_lib.encrypt(tokens["refresh_token"], env.secret_key),
        "connected_at": utcnow().isoformat(),
        "scopes": tokens.get("scope", ""),
    }
    await store.set_config(session, GMAIL_KEY, account)
    _log(session, "gmail", f"Gmail connected: {email}")
    await session.commit()
    return back("connected")


@router.post("/gmail/disconnect", status_code=204)
async def gmail_disconnect(session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)):
    account = await store.get_config(session, GMAIL_KEY)
    if account:
        try:
            await js.gmail.revoke(gmail_lib.decrypt(account["refresh_token"], get_env().secret_key))
        except GmailError:
            pass
        await store.set_config(session, GMAIL_KEY, {})
        _log(session, "gmail", f"Gmail disconnected: {account.get('email')}")
        await session.commit()


# --- extraction -----------------------------------------------------------------


@router.post("/extract", response_model=schemas.Extraction)
async def extract(body: schemas.ExtractIn, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)):
    s = await get_settings(session)
    result = await extraction.extract(body.text, js.llm, s.model, js.lookup)
    for check in result.emails:
        previous = await previous_application(session, check.email, result.company, s.duplicate_window_days)
        check.applied_before = previous.sent_at if previous else None
    return result


# --- applications ---------------------------------------------------------------


async def _resume(session: AsyncSession, resume_id: int | None) -> JobResume | None:
    if resume_id is None:
        return None
    resume = await session.get(JobResume, resume_id)
    if resume is None:
        raise HTTPException(404, "CV not found")
    return resume


async def _write(session: AsyncSession, js: JobServices, application: JobApplication) -> None:
    s = await get_settings(session)
    problem = js.llm.model_problem(s.model)
    if problem:
        raise HTTPException(409, problem)
    prompt = await active_prompt(session)
    details = schemas.Extraction(**application.details)
    try:
        subject, body = await write_email(
            js.llm,
            prompt.content if prompt else DEFAULT_PROMPT,
            application.source_text,
            details,
            await active_profile(session),
            application.resume,
            s,
        )
    except LLMError as e:
        raise HTTPException(502, f"The AI could not write the email: {e}") from e
    application.subject, application.body = subject, body
    application.prompt_id, application.model = (prompt.id if prompt else None), s.model
    application.status, application.error = ApplicationStatus.DRAFT, None


@router.post("/applications", response_model=schemas.ApplicationOut)
async def create_application(
    body: schemas.ApplicationCreate, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)
):
    resume = await _resume(session, body.resume_id)
    application = JobApplication(
        source_text=body.source_text,
        details=body.details.model_dump(mode="json"),
        company=body.details.company[:200],
        role=body.details.role[:200],
        location=body.details.location[:200],
        to_email=str(body.to_email).lower(),
        cc=[str(c).lower() for c in body.cc],
        resume_id=resume.id if resume else None,
        resume=resume,
    )
    await _write(session, js, application)
    session.add(application)
    await session.flush()
    _log(session, "draft", f"Draft written: {application.role or 'role'} at {application.company or application.to_email}")
    await session.commit()
    return application


@router.get("/applications", response_model=Page[schemas.ApplicationBrief])
async def list_applications(
    status: Literal["draft", "sending", "sent", "failed"] | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    query = select(JobApplication).order_by(JobApplication.created_at.desc(), JobApplication.id.desc())
    if status:
        query = query.where(JobApplication.status == status)
    if params.q:
        query = query.where(
            contains(params.q, JobApplication.company, JobApplication.role, JobApplication.to_email, JobApplication.subject)
        )
    return await paginate(session, query, params)


async def _application(session: AsyncSession, application_id: int) -> JobApplication:
    application = await session.get(JobApplication, application_id)
    if application is None:
        raise HTTPException(404, "Application not found")
    return application


def _editable(application: JobApplication) -> None:
    if application.status not in (ApplicationStatus.DRAFT, ApplicationStatus.FAILED):
        raise HTTPException(409, f"This application is {application.status} and can no longer be changed")


@router.get("/applications/{application_id}", response_model=schemas.ApplicationOut)
async def get_application(application_id: int, session: AsyncSession = Depends(get_session)):
    return await _application(session, application_id)


@router.patch("/applications/{application_id}", response_model=schemas.ApplicationOut)
async def update_application(application_id: int, body: schemas.ApplicationUpdate, session: AsyncSession = Depends(get_session)):
    application = await _application(session, application_id)
    _editable(application)
    changes = body.model_dump(exclude_unset=True, exclude={"clear_resume", "resume_id"})
    for field, value in changes.items():
        if field == "to_email":
            value = str(value).lower()
        elif field == "cc":
            value = [str(c).lower() for c in value]
        setattr(application, field, value)
    if body.clear_resume:
        application.resume_id, application.resume = None, None
    elif body.resume_id is not None:
        resume = await _resume(session, body.resume_id)
        application.resume_id, application.resume = resume.id, resume
    await session.commit()
    await session.refresh(application)
    return application


@router.post("/applications/{application_id}/rewrite", response_model=schemas.ApplicationOut)
async def rewrite_application(
    application_id: int, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)
):
    application = await _application(session, application_id)
    _editable(application)
    await _write(session, js, application)
    await session.commit()
    return application


@router.delete("/applications/{application_id}", status_code=204)
async def delete_application(application_id: int, session: AsyncSession = Depends(get_session)):
    application = await _application(session, application_id)
    _editable(application)
    await session.delete(application)
    await session.commit()


@router.post("/applications/{application_id}/send", response_model=schemas.ApplicationOut)
async def send_application(
    application_id: int,
    body: schemas.SendIn,
    session: AsyncSession = Depends(get_session),
    js: JobServices = Depends(job_services),
):
    env = get_env()
    s = await get_settings(session)
    application = await _application(session, application_id)
    _editable(application)

    account = await store.get_config(session, GMAIL_KEY)
    if not account:
        raise HTTPException(409, "Connect Gmail in Jobs settings first")
    if await sent_today(session) >= s.daily_send_limit:
        raise HTTPException(409, f"Daily send limit reached ({s.daily_send_limit}). It resets at 00:00 UTC.")
    problem = email_problem(application.subject, application.body, s)
    if problem:
        raise HTTPException(422, f"The email needs fixing, it is {problem}")
    check = await extraction.check_email(application.to_email, js.lookup)
    if not check.valid:
        raise HTTPException(422, f"{application.to_email}: {check.reason}")
    if not body.allow_duplicate:
        previous = await previous_application(
            session, application.to_email, application.company, s.duplicate_window_days, exclude_id=application.id
        )
        if previous:
            raise HTTPException(
                409,
                f"duplicate: you applied to {previous.company or previous.to_email} on {previous.sent_at:%d %b %Y}. "
                "Send anyway to confirm.",
            )

    # Claim it, so a double click or a second tab can never send the same email twice.
    claimed = await session.execute(
        update(JobApplication)
        .where(
            JobApplication.id == application_id,
            JobApplication.status.in_([ApplicationStatus.DRAFT, ApplicationStatus.FAILED]),
        )
        .values(status=ApplicationStatus.SENDING, error=None)
    )
    await session.commit()
    if claimed.rowcount != 1:
        raise HTTPException(409, "This application is already being sent")

    application = await session.get(JobApplication, application_id, populate_existing=True)
    attachment = None
    if application.resume_id:
        data = await session.scalar(select(JobResume.data).where(JobResume.id == application.resume_id))
        resume = application.resume
        attachment = Attachment(resume.filename, resume.content_type, data)
    message = gmail_lib.build_message(
        sender_email=account["email"],
        sender_name=s.sender_name,
        to=application.to_email,
        cc=application.cc,
        subject=application.subject,
        body=application.body,
        attachment=attachment,
    )
    try:
        result = await js.gmail.send(gmail_lib.decrypt(account["refresh_token"], env.secret_key), message)
    except GmailError as e:
        application.status, application.error = ApplicationStatus.FAILED, str(e)
        _log(session, "send_failed", f"{application.to_email}: {e}", "error")
        await session.commit()
        raise HTTPException(502, str(e)) from e

    application.status = ApplicationStatus.SENT
    application.sent_at = utcnow()
    application.gmail_message_id = result.get("id")
    application.gmail_thread_id = result.get("threadId")
    _log(session, "sent", f"Sent to {application.to_email}: {application.subject}")
    await session.commit()
    await session.refresh(application)
    return application


# --- profile --------------------------------------------------------------------


@router.get("/profile", response_model=Page[schemas.ProfileItemOut])
async def list_profile(
    kind: schemas.ProfileKind | None = None, params: PageParams = Depends(), session: AsyncSession = Depends(get_session)
):
    query = select(JobProfileItem).order_by(JobProfileItem.kind, JobProfileItem.id)
    if kind:
        query = query.where(JobProfileItem.kind == kind)
    if params.q:
        query = query.where(contains(params.q, JobProfileItem.title, JobProfileItem.content))
    return await paginate(session, query, params)


@router.post("/profile", response_model=schemas.ProfileItemOut)
async def create_profile_item(body: schemas.ProfileItemIn, session: AsyncSession = Depends(get_session)):
    item = JobProfileItem(**body.model_dump())
    session.add(item)
    await session.commit()
    return item


@router.put("/profile/{item_id}", response_model=schemas.ProfileItemOut)
async def update_profile_item(item_id: int, body: schemas.ProfileItemIn, session: AsyncSession = Depends(get_session)):
    item = await session.get(JobProfileItem, item_id)
    if item is None:
        raise HTTPException(404, "Profile item not found")
    for field, value in body.model_dump().items():
        setattr(item, field, value)
    await session.commit()
    return item


@router.delete("/profile/{item_id}", status_code=204)
async def delete_profile_item(item_id: int, session: AsyncSession = Depends(get_session)):
    item = await session.get(JobProfileItem, item_id)
    if item is None:
        raise HTTPException(404, "Profile item not found")
    await session.delete(item)
    await session.commit()


# --- CVs ------------------------------------------------------------------------


@router.get("/resumes", response_model=list[schemas.ResumeOut])
async def list_resumes(session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(JobResume).order_by(JobResume.is_default.desc(), JobResume.created_at.desc())))


@router.post("/resumes", response_model=schemas.ResumeOut)
async def upload_resume(
    file: UploadFile = File(...), name: str = Form("", max_length=120), session: AsyncSession = Depends(get_session)
):
    content_type = file.content_type or ""
    filename = (file.filename or "cv").rsplit("/", 1)[-1].rsplit("\\", 1)[-1][:255]
    if content_type not in RESUME_TYPES and not filename.lower().endswith(tuple(RESUME_TYPES.values())):
        raise HTTPException(415, "Upload a PDF or Word (.docx) file")
    data = await file.read(MAX_RESUME_BYTES + 1)
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(413, "The file is larger than 5 MB")
    if not data:
        raise HTTPException(422, "The file is empty")
    if filename.lower().endswith(".pdf") and not data.startswith(b"%PDF"):
        raise HTTPException(415, "This file is not a valid PDF")
    if content_type not in RESUME_TYPES:
        content_type = next(t for t, ext in RESUME_TYPES.items() if filename.lower().endswith(ext))

    first = not await session.scalar(select(func.count()).select_from(JobResume))
    resume = JobResume(
        name=name.strip() or filename.rsplit(".", 1)[0][:120],
        filename=filename,
        content_type=content_type,
        size=len(data),
        data=data,
        is_default=first,
    )
    session.add(resume)
    await session.commit()
    return resume


@router.get("/resumes/{resume_id}/file")
async def download_resume(resume_id: int, session: AsyncSession = Depends(get_session)):
    resume = await session.get(JobResume, resume_id)
    if resume is None:
        raise HTTPException(404, "CV not found")
    data = await session.scalar(select(JobResume.data).where(JobResume.id == resume_id))
    return Response(
        data,
        media_type=resume.content_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(resume.filename)}"},
    )


@router.post("/resumes/{resume_id}/default", response_model=schemas.ResumeOut)
async def make_default_resume(resume_id: int, session: AsyncSession = Depends(get_session)):
    resume = await session.get(JobResume, resume_id)
    if resume is None:
        raise HTTPException(404, "CV not found")
    await session.execute(update(JobResume).values(is_default=False))
    resume.is_default = True
    await session.commit()
    return resume


@router.delete("/resumes/{resume_id}", status_code=204)
async def delete_resume(resume_id: int, session: AsyncSession = Depends(get_session)):
    resume = await session.get(JobResume, resume_id)
    if resume is None:
        raise HTTPException(404, "CV not found")
    await session.delete(resume)
    await session.commit()


# --- prompt ---------------------------------------------------------------------


@router.get("/prompts", response_model=Page[schemas.PromptOut])
async def list_prompts(params: PageParams = Depends(), session: AsyncSession = Depends(get_session)):
    query = select(JobPrompt).where(JobPrompt.kind == "application").order_by(JobPrompt.version.desc())
    if params.q:
        query = query.where(contains(params.q, JobPrompt.content, JobPrompt.note))
    return await paginate(session, query, params)


@router.get("/prompts/current")
async def current_prompt(session: AsyncSession = Depends(get_session)) -> dict:
    """The active prompt, or the built-in one when none has been saved."""
    prompt = await active_prompt(session)
    if prompt:
        return {"content": prompt.content, "version": prompt.version, "builtin": False}
    return {"content": DEFAULT_PROMPT, "version": None, "builtin": True}


@router.post("/prompts", response_model=schemas.PromptOut)
async def create_prompt(body: schemas.PromptIn, session: AsyncSession = Depends(get_session)):
    last = await session.scalar(select(func.max(JobPrompt.version)).where(JobPrompt.kind == "application")) or 0
    await session.execute(update(JobPrompt).where(JobPrompt.kind == "application").values(is_active=False))
    prompt = JobPrompt(kind="application", version=last + 1, content=body.content, note=body.note, is_active=True)
    session.add(prompt)
    await session.commit()
    return prompt


@router.post("/prompts/{prompt_id}/activate", response_model=schemas.PromptOut)
async def activate_prompt(prompt_id: int, session: AsyncSession = Depends(get_session)):
    prompt = await session.get(JobPrompt, prompt_id)
    if prompt is None:
        raise HTTPException(404, "Prompt not found")
    await session.execute(update(JobPrompt).where(JobPrompt.kind == prompt.kind).values(is_active=False))
    prompt.is_active = True
    await session.commit()
    return prompt

