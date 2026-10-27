"""HTTP API of the Outreach service, under /api/outreach."""

import asyncio
import csv
import io
from datetime import timedelta
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile
from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.jobs import extract as extraction
from app.jobs import gmail as gmail_lib
from app.jobs import accounts
from app.jobs.api import JobServices, job_services
from app.jobs.gmail import Attachment, GmailError
from app.jobs.mailbox import open_mailbox
from app.jobs.models import GmailAccount, JobResume
from app.models import utcnow
from app.outreach import engine, importer, render, writer
from app.outreach import schemas
from app.outreach.models import Campaign, CampaignStatus, OutreachTemplate, Recipient, RecipientStatus, Suppression
from app.pagination import Page, PageParams, contains, paginate
from app.security import require_user
from app.services import store
from app.services.llm import LLMError

MAX_IMPORT = 5000
MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_RECIPIENTS = 20000
EDITABLE_RECIPIENT = (RecipientStatus.PENDING, RecipientStatus.FAILED, RecipientStatus.SKIPPED)

router = APIRouter(prefix="/api/outreach", dependencies=[Depends(require_user)])


def _log(session: AsyncSession, event: str, message: str, level: str = "info") -> None:
    store.log_event(session, f"outreach_{event}", message, level)


async def _campaign(session: AsyncSession, campaign_id: int) -> Campaign:
    campaign = await session.get(Campaign, campaign_id)
    if campaign is None:
        raise HTTPException(404, "Campaign not found")
    return campaign


async def _recipient(session: AsyncSession, campaign_id: int, recipient_id: int) -> Recipient:
    recipient = await session.get(Recipient, recipient_id)
    if recipient is None or recipient.campaign_id != campaign_id:
        raise HTTPException(404, "Recipient not found")
    return recipient


def _open(campaign: Campaign) -> None:
    if campaign.status == CampaignStatus.CANCELLED:
        raise HTTPException(409, "This campaign was cancelled. Make a new campaign to send more.")


def _reopen(campaign: Campaign, why: str = "there are new recipients") -> None:
    """A finished campaign that gets someone new to write to waits, paused, for the user to resume it."""
    if campaign.status == CampaignStatus.COMPLETED:
        campaign.status, campaign.finished_at = CampaignStatus.PAUSED, None
        campaign.pause_reason = f"Reopened: {why}. Resume to send."


async def _counts(session: AsyncSession, campaign_id: int) -> dict[str, int]:
    rows = await session.execute(select(Recipient.status, func.count()).where(Recipient.campaign_id == campaign_id).group_by(Recipient.status))
    return dict(rows.all())


async def _scheduled(session: AsyncSession, campaign: Campaign) -> int:
    """People written to who still have a follow-up ahead of them."""
    if not campaign.followups:
        return 0
    query = select(func.count()).select_from(Recipient).where(
        Recipient.campaign_id == campaign.id,
        Recipient.status == RecipientStatus.SENT,
        Recipient.followups_sent < len(campaign.followups),
    )
    return await session.scalar(query) or 0


async def _columns(session: AsyncSession, campaign_id: int) -> list[str]:
    rows = await session.scalars(select(func.jsonb_object_keys(Recipient.fields)).where(Recipient.campaign_id == campaign_id).distinct())
    return sorted(rows)


async def _out(session: AsyncSession, campaign: Campaign) -> schemas.CampaignOut:
    now = utcnow()
    s = await engine.outreach_settings(session)
    waiting = None
    if campaign.status == CampaignStatus.RUNNING:
        waiting = await engine.waiting_reason(session, campaign, now, s)
    elif campaign.status == CampaignStatus.PAUSED:
        waiting = campaign.pause_reason or "Paused"
    out = schemas.CampaignOut.model_validate(campaign)
    return out.model_copy(
        update={
            "counts": await _counts(session, campaign.id),
            "sent_24h": await engine.delivered_since(session, now - timedelta(hours=24), now, campaign.id),
            "waiting": waiting,
            "columns": await _columns(session, campaign.id),
            "followups_sent": await session.scalar(select(func.coalesce(func.sum(Recipient.followups_sent), 0)).where(Recipient.campaign_id == campaign.id)) or 0,
            "followups_scheduled": await _scheduled(session, campaign),
        }
    )


# --- overview and settings --------------------------------------------------------


@router.get("/overview")
async def overview(session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)) -> dict:
    now = utcnow()
    s = await engine.outreach_settings(session)
    account = await accounts.default_account(session)
    campaigns = dict((await session.execute(select(Campaign.status, func.count()).group_by(Campaign.status))).all())
    recipients = dict((await session.execute(select(Recipient.status, func.count()).group_by(Recipient.status))).all())
    recent = list(await session.scalars(select(Campaign).order_by(Campaign.created_at.desc()).limit(5)))
    return {
        "gmail": {"configured": js.gmail.configured, "connected": account is not None, "email": account.email if account else None},
        "ai_problem": js.llm.model_problem(s.model),
        "sent_24h": await engine.delivered_since(session, now - timedelta(hours=24), now),
        "daily_limit": s.daily_limit,
        "campaigns": campaigns,
        "recipients": recipients,
        "suppressed": await session.scalar(select(func.count()).select_from(Suppression)) or 0,
        "recent": [schemas.CampaignListItem(**schemas.CampaignBrief.model_validate(c).model_dump(), counts=await _counts(session, c.id)) for c in recent],
    }


@router.get("/settings", response_model=schemas.OutreachSettings)
async def read_settings(session: AsyncSession = Depends(get_session)):
    return await engine.outreach_settings(session)


@router.put("/settings", response_model=schemas.OutreachSettings)
async def write_settings(body: schemas.OutreachSettings, session: AsyncSession = Depends(get_session)):
    await store.set_config(session, engine.SETTINGS_KEY, body.model_dump())
    _log(session, "settings", "Outreach settings saved")
    await session.commit()
    return body


# --- templates --------------------------------------------------------------------


@router.get("/templates", response_model=list[schemas.TemplateOut])
async def list_templates(session: AsyncSession = Depends(get_session)):
    return list(await session.scalars(select(OutreachTemplate).order_by(OutreachTemplate.name)))


@router.post("/templates", response_model=schemas.TemplateOut)
async def create_template(body: schemas.TemplateIn, session: AsyncSession = Depends(get_session)):
    template = OutreachTemplate(**body.model_dump())
    session.add(template)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, f"A template named '{body.name}' already exists") from None
    return template


@router.put("/templates/{template_id}", response_model=schemas.TemplateOut)
async def update_template(template_id: int, body: schemas.TemplateIn, session: AsyncSession = Depends(get_session)):
    template = await session.get(OutreachTemplate, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    for field, value in body.model_dump().items():
        setattr(template, field, value)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(409, f"A template named '{body.name}' already exists") from None
    return template


@router.delete("/templates/{template_id}", status_code=204)
async def delete_template(template_id: int, session: AsyncSession = Depends(get_session)):
    template = await session.get(OutreachTemplate, template_id)
    if template is None:
        raise HTTPException(404, "Template not found")
    await session.delete(template)
    await session.commit()


@router.post("/templates/generate", response_model=schemas.GeneratedEmail)
async def generate_template(
    body: schemas.GenerateIn, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)
):
    """Write a template from a short description. The result is returned for editing, nothing is saved."""
    s = await engine.outreach_settings(session)
    problem = js.llm.model_problem(s.model)
    if problem:
        raise HTTPException(409, problem)
    try:
        subject, text = await writer.generate_template(js.llm, s.model, body.brief, body.tone, body.language, body.variables)
    except LLMError as e:
        raise HTTPException(502, f"The AI could not write the template: {e}") from e
    return schemas.GeneratedEmail(subject=subject, body=text)


# --- campaigns --------------------------------------------------------------------


async def _check_account(session: AsyncSession, account_id: int | None) -> None:
    if account_id is not None and await session.get(GmailAccount, account_id) is None:
        raise HTTPException(404, "Gmail account not found")


async def _resume_for(session: AsyncSession, resume_id: int | None) -> JobResume | None:
    if resume_id is None:
        return None
    resume = await session.get(JobResume, resume_id)
    if resume is None:
        raise HTTPException(404, "CV not found")
    return resume


def _validated(data: dict) -> schemas.CampaignIn:
    try:
        return schemas.CampaignIn(**data)
    except ValidationError as e:
        first = e.errors()[0]
        raise HTTPException(422, f"{'.'.join(str(p) for p in first['loc'])}: {first['msg'].removeprefix('Value error, ')}") from None


@router.post("/campaigns", response_model=schemas.CampaignOut)
async def create_campaign(body: schemas.CampaignIn, session: AsyncSession = Depends(get_session)):
    resume = await _resume_for(session, body.resume_id)
    await _check_account(session, body.gmail_account_id)
    campaign = Campaign(**body.model_dump(), resume=resume)
    session.add(campaign)
    await session.flush()
    _log(session, "campaign", f"Campaign created: {campaign.name}")
    await session.commit()
    return await _out(session, campaign)


@router.get("/campaigns", response_model=Page[schemas.CampaignListItem])
async def list_campaigns(
    status: Literal["draft", "running", "paused", "completed", "cancelled"] | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    query = select(Campaign).order_by(Campaign.created_at.desc(), Campaign.id.desc())
    if status:
        query = query.where(Campaign.status == status)
    if params.q:
        query = query.where(contains(params.q, Campaign.name))
    page = await paginate(session, query, params)
    page["items"] = [
        schemas.CampaignListItem(**schemas.CampaignBrief.model_validate(c).model_dump(), counts=await _counts(session, c.id))
        for c in page["items"]
    ]
    return page


@router.get("/campaigns/{campaign_id}", response_model=schemas.CampaignOut)
async def get_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    return await _out(session, await _campaign(session, campaign_id))


@router.patch("/campaigns/{campaign_id}", response_model=schemas.CampaignOut)
async def update_campaign(campaign_id: int, body: schemas.CampaignPatch, session: AsyncSession = Depends(get_session)):
    campaign = await _campaign(session, campaign_id)
    _open(campaign)
    changes = body.model_dump(exclude_unset=True, exclude={"clear_resume"})
    if "mode" in changes and changes["mode"] != campaign.mode and campaign.status == CampaignStatus.RUNNING:
        raise HTTPException(409, "Pause the campaign before changing how its emails are written")
    current = schemas.CampaignIn.model_validate(campaign, from_attributes=True).model_dump()
    merged = _validated({**current, **{k: v for k, v in changes.items() if v is not None or k in ("resume_id", "gmail_account_id")}})
    if body.clear_resume:
        merged.resume_id = None
    resume = await _resume_for(session, merged.resume_id)
    await _check_account(session, merged.gmail_account_id)
    if merged.model_dump()["followups"] != campaign.followups:
        _reopen(campaign, "a follow-up was added")  # a finished campaign with a new follow-up has more to send
    for field, value in merged.model_dump().items():
        setattr(campaign, field, value)
    campaign.resume = resume
    await session.commit()
    return await _out(session, campaign)


@router.delete("/campaigns/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await _campaign(session, campaign_id)
    if campaign.status == CampaignStatus.RUNNING:
        raise HTTPException(409, "Pause the campaign before deleting it")
    if await session.scalar(select(func.count()).select_from(Recipient).where(Recipient.campaign_id == campaign_id, Recipient.sent_at.is_not(None))):
        # The send history is what stops the same person being written to twice, so it is kept.
        raise HTTPException(409, "This campaign has sent emails. Cancel it instead, the history is kept.")
    await session.delete(campaign)
    await session.commit()


async def _pending(session: AsyncSession, campaign_id: int) -> list[Recipient]:
    return list(
        await session.scalars(
            select(Recipient)
            .where(Recipient.campaign_id == campaign_id, Recipient.status == RecipientStatus.PENDING)
            .order_by(Recipient.position, Recipient.id)
            .limit(MAX_IMPORT)
        )
    )


async def _check(session: AsyncSession, js: JobServices, campaign: Campaign) -> schemas.Check:
    s = await engine.outreach_settings(session)
    jobs = await engine.campaign_identity(session, campaign)
    pending = await _pending(session, campaign.id)
    blockers: list[str] = []
    warnings: list[str] = []

    account = await accounts.resolve(session, campaign.gmail_account_id)
    if account is None:
        blockers.append(
            "Connect Gmail in Email settings first."
            if campaign.gmail_account_id is None
            else "The Gmail this campaign sends from was disconnected. Choose another one in the campaign."
        )
    if not pending and not await _scheduled(session, campaign):
        blockers.append("There is nobody left to send to. Add recipients first.")

    missing_examples: list[schemas.MissingVariables] = []
    with_missing = 0
    if campaign.mode == "ai":
        if not campaign.ai_brief.strip():
            blockers.append("Describe what the AI should write about (the brief).")
        problem = js.llm.model_problem(s.model)
        if problem:
            blockers.append(f"The AI model is unavailable: {problem}")
    else:
        without_content = [r for r in pending if not r.body.strip()]
        if without_content and not campaign.body_template.strip():
            blockers.append(f"{len(without_content)} recipient(s) have no message and the campaign has no template.")
        if not campaign.subject_template.strip() and any(not r.subject.strip() for r in pending):
            blockers.append("Some recipients have no subject and the campaign has no subject line.")
    if not blockers:
        for r in pending:
            if campaign.mode == "ai" and not r.body:
                continue
            missing = engine.compose(campaign, r, jobs).missing
            if missing:
                with_missing += 1
                if len(missing_examples) < 20:
                    missing_examples.append(schemas.MissingVariables(id=r.id, email=r.email, missing=missing))
    if with_missing:
        warnings.append(f"{with_missing} recipient(s) lack a value used by the template. They will be marked failed instead of being sent a broken email.")

    now = utcnow()
    reason = engine.window_reason(campaign, now)
    if reason and campaign.status != CampaignStatus.RUNNING:
        warnings.append(reason + ".")
    wants_cv = [i + 1 for i, f in enumerate(campaign.followups) if f.get("attach_resume")]
    if wants_cv and not campaign.resume_id:
        blockers.append(f"Follow-up {', '.join(map(str, wants_cv))} should carry the CV, but no CV is chosen for the campaign.")
    if campaign.followups:
        days = [f["days"] for f in campaign.followups]
        warnings.append(
            f"{len(days)} follow-up(s), {', '.join(str(d) for d in days)} day(s) after the previous email. Anyone who replies or bounces is left alone."
        )
    if campaign.ramp_up:
        warnings.append(f"Warm-up is on: {engine.WARMUP_STEP} emails on day one, {engine.WARMUP_STEP} more each day up to {campaign.daily_limit}.")

    average = (campaign.min_delay_seconds + campaign.max_delay_seconds) / 2
    hours = campaign.window_end_hour - campaign.window_start_hour
    per_day = max(min(campaign.daily_limit, s.daily_limit, int(hours * 3600 / average)), 1)
    days = len(pending) / per_day * (7 / 5 if campaign.weekdays_only else 1)
    return schemas.Check(
        ready=not blockers,
        blockers=blockers,
        warnings=warnings,
        pending=len(pending),
        with_missing=with_missing,
        missing_examples=missing_examples,
        estimated_days=round(days, 1),
    )


@router.get("/campaigns/{campaign_id}/check", response_model=schemas.Check)
async def check_campaign(campaign_id: int, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)):
    return await _check(session, js, await _campaign(session, campaign_id))


@router.post("/campaigns/{campaign_id}/start", response_model=schemas.CampaignOut)
async def start_campaign(campaign_id: int, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)):
    campaign = await _campaign(session, campaign_id)
    _open(campaign)
    if campaign.status == CampaignStatus.RUNNING:
        return await _out(session, campaign)
    check = await _check(session, js, campaign)
    if check.blockers:
        raise HTTPException(409, " ".join(check.blockers))
    campaign.status, campaign.pause_reason, campaign.next_send_at = CampaignStatus.RUNNING, "", None
    campaign.started_at = campaign.started_at or utcnow()
    _log(session, "started", f"Campaign started: {campaign.name} ({check.pending} to send)")
    await session.commit()
    return await _out(session, campaign)


@router.post("/campaigns/{campaign_id}/pause", response_model=schemas.CampaignOut)
async def pause_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await _campaign(session, campaign_id)
    if campaign.status != CampaignStatus.RUNNING:
        raise HTTPException(409, f"This campaign is {campaign.status}, not running")
    campaign.status, campaign.pause_reason, campaign.next_send_at = CampaignStatus.PAUSED, "Paused by you", None
    _log(session, "paused", f"Campaign paused: {campaign.name}")
    await session.commit()
    return await _out(session, campaign)


@router.post("/campaigns/{campaign_id}/cancel", response_model=schemas.CampaignOut)
async def cancel_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await _campaign(session, campaign_id)
    _open(campaign)
    await session.execute(
        update(Recipient)
        .where(Recipient.campaign_id == campaign_id, Recipient.status == RecipientStatus.PENDING)
        .values(status=RecipientStatus.SKIPPED, error="Campaign cancelled")
    )
    campaign.status, campaign.finished_at, campaign.next_send_at = CampaignStatus.CANCELLED, utcnow(), None
    _log(session, "cancelled", f"Campaign cancelled: {campaign.name}")
    await session.commit()
    return await _out(session, campaign)


# --- recipients -------------------------------------------------------------------


@router.post("/campaigns/{campaign_id}/recipients/import", response_model=schemas.ImportOut)
async def import_recipients(
    campaign_id: int,
    body: schemas.ImportIn,
    session: AsyncSession = Depends(get_session),
    js: JobServices = Depends(job_services),
):
    campaign = await _campaign(session, campaign_id)
    _open(campaign)
    return await _add_recipients(session, js, campaign, importer.parse(body.text), body.skip_recent, body.check_domains)


@router.post("/campaigns/{campaign_id}/recipients/import-file", response_model=schemas.ImportOut)
async def import_recipients_file(
    campaign_id: int,
    file: UploadFile = File(...),
    skip_recent: bool = Form(True),
    check_domains: bool = Form(True),
    session: AsyncSession = Depends(get_session),
    js: JobServices = Depends(job_services),
):
    """An Excel (.xlsx) file, or a CSV/TSV/text file, read exactly like pasted text."""
    campaign = await _campaign(session, campaign_id)
    _open(campaign)
    data = await file.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "The file is larger than 5 MB. Split it and import in parts.")
    if (file.filename or "").lower().endswith(".xlsx"):
        try:
            sheet = importer.parse_xlsx(data)
        except ValueError as e:
            raise HTTPException(415, str(e)) from None
    else:
        try:
            sheet = importer.parse(data.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise HTTPException(415, "Save the file as .xlsx or as UTF-8 CSV") from None
    return await _add_recipients(session, js, campaign, sheet, skip_recent, check_domains)


def _rewrite_recipient(recipient: Recipient, row: importer.Row) -> int:
    """Replace what the import brings (a blank cell keeps what is there). 1 when something changed."""
    changes = {
        "name": row.name,
        "company": row.company,
        "subject": row.subject,
        "body": row.body,
    }
    changed = False
    for key, value in changes.items():
        if value and getattr(recipient, key) != value:
            setattr(recipient, key, value)
            changed = True
    merged = {**recipient.fields, **{k: v for k, v in row.fields.items() if v}}
    if merged != recipient.fields:
        recipient.fields, changed = merged, True
    # A failure caused by the old content gets another go. One that may have gone out is left for a person to check.
    unsafe = ("Outcome unknown", "stopped while sending")
    if changed and recipient.status == RecipientStatus.FAILED and not any(w in (recipient.error or "") for w in unsafe):
        recipient.status, recipient.error, recipient.attempts, recipient.retry_at = RecipientStatus.PENDING, None, 0, None
    return int(changed)


def _import_warnings(sheet: importer.Sheet) -> list[str]:
    """A column full of long text that was not taken as the message is almost always a message with an unexpected name."""
    if any(row.body for row in sheet.rows):
        return []
    found = []
    for column in sheet.columns:
        cells = [row.fields[column] for row in sheet.rows if row.fields.get(column)]
        if cells and sum(len(c) for c in cells) / len(cells) > 200:
            found.append(
                f"The column '{column}' holds long text but was not used as the message, so those emails will use the campaign template. "
                "Rename the column to 'body' (or 'email body') and import the list again to send its text as written."
            )
    return found


async def _add_recipients(
    session: AsyncSession, js: JobServices, campaign: Campaign, sheet: importer.Sheet, skip_recent: bool, check_domains: bool
) -> schemas.ImportOut:
    campaign_id = campaign.id
    if len(sheet.rows) > MAX_IMPORT:
        raise HTTPException(413, f"{len(sheet.rows)} addresses in one go is too many. Import at most {MAX_IMPORT} at a time.")
    existing_count = await session.scalar(select(func.count()).select_from(Recipient).where(Recipient.campaign_id == campaign_id)) or 0

    rejected = [schemas.RejectedRow(line=r.line, value=r.value, reason=r.reason) for r in sheet.rejected]
    existing = {r.email: r for r in await session.scalars(select(Recipient).where(Recipient.campaign_id == campaign_id))}
    rows = []
    updated = 0
    for row in sheet.rows:
        known = existing.get(row.email)
        if known is None:
            rows.append(row)
        elif known.status in EDITABLE_RECIPIENT:
            # Not written to yet, so importing the list again with better content corrects them. Anyone emailed is never touched.
            if _rewrite_recipient(known, row):
                updated += 1
            else:
                rejected.append(schemas.RejectedRow(line=row.line, value=row.email, reason="Already in this campaign"))
        else:
            rejected.append(
                schemas.RejectedRow(line=row.line, value=row.email, reason=f"Already {known.status}, left unchanged and not written to again")
            )
    if existing_count + len(rows) > MAX_RECIPIENTS:
        raise HTTPException(413, f"A campaign holds at most {MAX_RECIPIENTS} recipients")

    s = await engine.outreach_settings(session)
    suppressed = set(await session.scalars(select(Suppression.email).where(Suppression.email.in_([r.email for r in rows])))) if rows else set()
    recent = {}
    if skip_recent:
        addresses = [r.email for r in rows]
        recent = await engine.recent_contacts(session, addresses, s.skip_recent_days)
        recent.update(await engine.replied_before(session, addresses))  # an answer outweighs "written to recently"

    bad_domains: dict[str, str] = {}
    if check_domains and rows:
        by_domain = {r.email.rsplit("@", 1)[1]: r.email for r in rows}
        gate = asyncio.Semaphore(20)

        async def look(email: str):
            async with gate:
                return await extraction.check_email(email, js.lookup)

        for check in await asyncio.gather(*(look(e) for e in by_domain.values())):
            if not check.valid:
                bad_domains[check.email.rsplit("@", 1)[1]] = check.reason

    position = (await session.scalar(select(func.max(Recipient.position)).where(Recipient.campaign_id == campaign_id))) or 0
    held_back = with_own_content = 0
    held_emails: set[str] = set()
    for row in rows:
        position += 1
        domain = row.email.rsplit("@", 1)[1]
        hold = (
            "On the do-not-contact list"
            if row.email in suppressed
            else bad_domains.get(domain) or recent.get(row.email)
        )
        held_back += bool(hold)
        if hold:
            held_emails.add(row.email)
        with_own_content += bool(row.body)
        session.add(
            Recipient(
                campaign_id=campaign_id,
                position=position,
                email=row.email,
                name=row.name,
                company=row.company,
                fields=row.fields,
                subject=row.subject,
                body=row.body,
                status=RecipientStatus.SKIPPED if hold else RecipientStatus.PENDING,
                error=hold or None,
            )
        )
    if updated or any(r for r in rows if r.email not in held_emails):
        _reopen(campaign)
    _log(
        session,
        "import",
        f"{len(rows)} recipient(s) added to '{campaign.name}', {updated} updated, {held_back} held back, {len(rejected)} rejected",
    )
    await session.commit()
    return schemas.ImportOut(
        added=len(rows),
        updated=updated,
        held_back=held_back,
        rejected=rejected[:100],
        rejected_total=len(rejected),
        with_own_content=with_own_content,
        warnings=_import_warnings(sheet),
        columns=sheet.columns,
    )


@router.get("/campaigns/{campaign_id}/recipients", response_model=Page[schemas.RecipientOut])
async def list_recipients(
    campaign_id: int,
    status: Literal["pending", "sending", "sent", "replied", "bounced", "failed", "skipped"] | None = None,
    params: PageParams = Depends(),
    session: AsyncSession = Depends(get_session),
):
    await _campaign(session, campaign_id)
    query = select(Recipient).where(Recipient.campaign_id == campaign_id).order_by(Recipient.position, Recipient.id)
    if status:
        query = query.where(Recipient.status == status)
    if params.q:
        query = query.where(contains(params.q, Recipient.email, Recipient.name, Recipient.company))
    return await paginate(session, query, params)


def _editable_recipient(recipient: Recipient) -> None:
    if recipient.status not in EDITABLE_RECIPIENT:
        raise HTTPException(409, f"This recipient is {recipient.status} and can no longer be changed")


@router.patch("/campaigns/{campaign_id}/recipients/{recipient_id}", response_model=schemas.RecipientOut)
async def update_recipient(
    campaign_id: int, recipient_id: int, body: schemas.RecipientPatch, session: AsyncSession = Depends(get_session)
):
    recipient = await _recipient(session, campaign_id, recipient_id)
    _editable_recipient(recipient)
    changes = body.model_dump(exclude_unset=True)
    if changes.get("email") is not None:
        address = importer.clean_address(changes["email"])
        if not address:
            raise HTTPException(422, f"{changes['email']} is not a valid email address")
        changes["email"] = address[0]
        taken = await session.scalar(
            select(Recipient.id).where(Recipient.campaign_id == campaign_id, Recipient.email == address[0], Recipient.id != recipient_id)
        )
        if taken:
            raise HTTPException(409, "That address is already in this campaign")
    if "subject" in changes:
        changes["subject"] = " ".join((changes["subject"] or "").split())
    for field, value in changes.items():
        if value is not None:
            setattr(recipient, field, value)
    await session.commit()
    return recipient


@router.post("/campaigns/{campaign_id}/recipients/{recipient_id}/retry", response_model=schemas.RecipientOut)
async def retry_recipient(
    campaign_id: int,
    recipient_id: int,
    allow_recent: bool = False,
    session: AsyncSession = Depends(get_session),
):
    """Put a failed or held-back recipient back in the queue. allow_recent overrides the 'written to recently' hold."""
    campaign = await _campaign(session, campaign_id)
    _open(campaign)
    recipient = await _recipient(session, campaign_id, recipient_id)
    _editable_recipient(recipient)
    if await engine.is_suppressed(session, recipient.email):
        raise HTTPException(409, "This address is on the do-not-contact list. Remove it there first.")
    recipient.status, recipient.error, recipient.attempts, recipient.retry_at = RecipientStatus.PENDING, None, 0, None
    recipient.allow_recent = recipient.allow_recent or allow_recent
    _reopen(campaign)
    await session.commit()
    return recipient


@router.delete("/campaigns/{campaign_id}/recipients/{recipient_id}", status_code=204)
async def delete_recipient(campaign_id: int, recipient_id: int, session: AsyncSession = Depends(get_session)):
    recipient = await _recipient(session, campaign_id, recipient_id)
    _editable_recipient(recipient)
    await session.delete(recipient)
    await session.commit()


@router.post("/campaigns/{campaign_id}/recipients/{recipient_id}/generate", response_model=schemas.RecipientOut)
async def generate_for_recipient(
    campaign_id: int, recipient_id: int, session: AsyncSession = Depends(get_session), js: JobServices = Depends(job_services)
):
    """Have the AI write (or rewrite) this one email from the campaign's brief, so it can be read before it is sent."""
    campaign = await _campaign(session, campaign_id)
    recipient = await _recipient(session, campaign_id, recipient_id)
    _editable_recipient(recipient)
    if not campaign.ai_brief.strip():
        raise HTTPException(409, "Add a brief to the campaign first")
    s = await engine.outreach_settings(session)
    jobs = await engine.campaign_identity(session, campaign)
    problem = js.llm.model_problem(s.model)
    if problem:
        raise HTTPException(409, problem)
    ctx = render.context(recipient.email, recipient.name, recipient.company, recipient.fields)
    try:
        recipient.subject, recipient.body = await writer.write_for_recipient(js.llm, s.model, campaign.ai_brief, ctx, jobs.sender_name)
    except LLMError as e:
        raise HTTPException(502, f"The AI could not write the email: {e}") from e
    recipient.error = None
    await session.commit()
    return recipient


@router.get("/campaigns/{campaign_id}/preview", response_model=schemas.Preview)
async def preview(
    campaign_id: int, recipient_id: int | None = None, step: int = 0, session: AsyncSession = Depends(get_session)
):
    """The email exactly as it will be sent to a recipient (the first in the queue by default).

    step 0 is the first email, 1 the first follow-up, and so on."""
    campaign = await _campaign(session, campaign_id)
    if recipient_id is not None:
        recipient = await _recipient(session, campaign_id, recipient_id)
    else:
        recipient = await session.scalar(
            select(Recipient).where(Recipient.campaign_id == campaign_id).order_by(Recipient.status != RecipientStatus.PENDING, Recipient.position, Recipient.id).limit(1)
        )
        if recipient is None:
            raise HTTPException(404, "Add recipients to see a preview")
    jobs = await engine.campaign_identity(session, campaign)
    if step > 0:
        if step > len(campaign.followups):
            raise HTTPException(404, "This campaign has no such follow-up")
        composed = engine.compose_followup(campaign, recipient, step - 1, jobs)
    else:
        composed = engine.compose(campaign, recipient, jobs)
    return schemas.Preview(
        recipient_id=recipient.id,
        email=recipient.email,
        subject=composed.subject,
        body=composed.body,
        missing=composed.missing,
        own_content=bool(recipient.body),
        step=step,
    )


@router.post("/campaigns/{campaign_id}/test-send")
async def test_send(
    campaign_id: int,
    body: schemas.TestSendIn,
    session: AsyncSession = Depends(get_session),
    js: JobServices = Depends(job_services),
) -> dict:
    """Send one rendered email to your own Gmail address, to see it as the recipient will."""
    campaign = await _campaign(session, campaign_id)
    account = await accounts.resolve(session, campaign.gmail_account_id)
    if account is None:
        raise HTTPException(409, "Connect Gmail in Email settings first")
    preview_ = await preview(campaign_id, body.recipient_id, 0, session)
    if preview_.missing:
        raise HTTPException(422, "Missing value for: " + ", ".join(preview_.missing))
    if not preview_.subject or not preview_.body.strip():
        raise HTTPException(422, "The email has no subject or no message yet")
    jobs = accounts.identity(await engine.jobs_settings(session), account)
    attachment = None
    if campaign.attach_first and campaign.resume_id and campaign.resume:
        data = await session.scalar(select(JobResume.data).where(JobResume.id == campaign.resume_id))
        attachment = Attachment(campaign.resume.filename, campaign.resume.content_type, data)
    message = gmail_lib.build_message(
        sender_email=account.email,
        sender_name=jobs.sender_name,
        to=account.email,
        cc=[],
        subject=f"[TEST] {preview_.subject}",
        body=preview_.body,
        attachment=attachment,
    )
    try:
        await open_mailbox(js, account).send(message)
    except GmailError as e:
        raise HTTPException(502, str(e)) from e
    return {"sent_to": account.email}


def _cell(value) -> str:
    """CSV cells that start with = + - @ would run as formulas in Excel, so they are made plain text."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/campaigns/{campaign_id}/export")
async def export_campaign(campaign_id: int, session: AsyncSession = Depends(get_session)):
    campaign = await _campaign(session, campaign_id)
    out = io.StringIO()
    writer_ = csv.writer(out)
    writer_.writerow(["email", "name", "company", "status", "sent_at", "follow_ups_sent", "subject", "error"])
    rows = await session.stream_scalars(select(Recipient).where(Recipient.campaign_id == campaign_id).order_by(Recipient.position, Recipient.id))
    async for r in rows:
        writer_.writerow([_cell(v) for v in (r.email, r.name, r.company, r.status, r.sent_at.isoformat() if r.sent_at else "", r.followups_sent, r.subject, r.error)])
    name = "".join(c if c.isalnum() else "-" for c in campaign.name)[:60] or "campaign"
    return Response(
        out.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}.csv"'},
    )


# --- do-not-contact list ----------------------------------------------------------


@router.get("/suppressions", response_model=Page[schemas.SuppressionOut])
async def list_suppressions(params: PageParams = Depends(), session: AsyncSession = Depends(get_session)):
    query = select(Suppression).order_by(Suppression.created_at.desc(), Suppression.id.desc())
    if params.q:
        query = query.where(contains(params.q, Suppression.email, Suppression.reason))
    return await paginate(session, query, params)


@router.post("/suppressions", response_model=dict)
async def add_suppressions(body: schemas.SuppressionIn, session: AsyncSession = Depends(get_session)):
    """Add every address found in the text. Pending emails to them are held back."""
    sheet = importer.parse(body.emails)
    emails = [r.email for r in sheet.rows]
    known = set(await session.scalars(select(Suppression.email).where(Suppression.email.in_(emails)))) if emails else set()
    new = [e for e in emails if e not in known]
    for email in new:
        session.add(Suppression(email=email, reason=body.reason))
    if new:
        await session.execute(
            update(Recipient)
            .where(Recipient.email.in_(new), Recipient.status == RecipientStatus.PENDING)
            .values(status=RecipientStatus.SKIPPED, error="On the do-not-contact list")
        )
        _log(session, "suppressed", f"{len(new)} address(es) added to the do-not-contact list")
    await session.commit()
    return {"added": len(new), "already_listed": len(known), "ignored": len(sheet.rejected)}


@router.delete("/suppressions/{suppression_id}", status_code=204)
async def delete_suppression(suppression_id: int, session: AsyncSession = Depends(get_session)):
    row = await session.get(Suppression, suppression_id)
    if row is None:
        raise HTTPException(404, "Not found")
    await session.delete(row)
    await session.commit()
