"""The sender: works through running campaigns slowly and safely, one email at a time.

`tick` is called every few seconds. Each call sends at most one email, and only when every rule allows it:
the campaign's sending window and pace, its daily limit (with warm-up), and the account-wide limit and gap.
Every claim is a compare-and-set in the database, so two server instances can run `tick` without sending twice.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_env
from app.jobs import gmail as gmail_lib
from app.jobs.gmail import Attachment, GmailError
from app.jobs.models import ApplicationStatus, JobApplication, JobResume
from app.jobs.schemas import JobSettings
from app.models import utcnow
from app.outreach import render, writer
from app.outreach.models import Campaign, CampaignStatus, Recipient, RecipientStatus, Suppression
from app.outreach.schemas import OutreachSettings
from app.services import store
from app.services.llm import LLMError

logger = logging.getLogger("easybid")

SETTINGS_KEY = "outreach_settings"
JOBS_SETTINGS_KEY = "jobs_settings"
GMAIL_KEY = "jobs_gmail"

MAX_ATTEMPTS = 3
STUCK_AFTER = timedelta(minutes=10)  # a recipient stuck in "sending" means the server stopped mid-send
REPLY_WINDOW = timedelta(days=14)  # how long after sending a thread is watched for replies and bounces
WARMUP_STEP = 10  # emails more per day while a campaign warms up
GENERATE_PER_TICK = 2
CHECKS_PER_TICK = 5
MIN_SENT_FOR_BOUNCE_RATE = 10


async def outreach_settings(session: AsyncSession) -> OutreachSettings:
    return OutreachSettings(**await store.get_config(session, SETTINGS_KEY))


async def jobs_settings(session: AsyncSession) -> JobSettings:
    return JobSettings(**await store.get_config(session, JOBS_SETTINGS_KEY))


# --- rules ------------------------------------------------------------------------


def next_window_open(campaign: Campaign, now: datetime) -> datetime:
    local = now.astimezone(ZoneInfo(campaign.timezone))
    for days in range(9):
        opens = (local + timedelta(days=days)).replace(hour=campaign.window_start_hour, minute=0, second=0, microsecond=0)
        if opens > local and (not campaign.weekdays_only or opens.weekday() < 5):
            return opens
    return local


def window_reason(campaign: Campaign, now: datetime) -> str | None:
    local = now.astimezone(ZoneInfo(campaign.timezone))
    if (not campaign.weekdays_only or local.weekday() < 5) and campaign.window_start_hour <= local.hour < campaign.window_end_hour:
        return None
    return f"Outside the sending window. Next send {next_window_open(campaign, now):%a %H:%M} ({campaign.timezone})"


def daily_allowance(campaign: Campaign, now: datetime) -> int:
    """The campaign's daily limit, lowered while it is warming up."""
    if campaign.ramp_up and campaign.started_at:
        days = max((now - campaign.started_at).days, 0)
        return min(campaign.daily_limit, WARMUP_STEP * (days + 1))
    return campaign.daily_limit


async def delivered_since(session: AsyncSession, since: datetime, now: datetime, campaign_id: int | None = None) -> int:
    query = select(func.count()).select_from(Recipient).where(Recipient.sent_at > since, Recipient.sent_at <= now)
    if campaign_id is not None:
        return await session.scalar(query.where(Recipient.campaign_id == campaign_id)) or 0
    applications = select(func.count()).where(
        JobApplication.status == ApplicationStatus.SENT, JobApplication.sent_at > since, JobApplication.sent_at <= now
    )
    # One Gmail account sends both, so both count against its limit.
    return (await session.scalar(query) or 0) + (await session.scalar(applications) or 0)


async def last_send(session: AsyncSession, now: datetime) -> datetime | None:
    return await session.scalar(select(func.max(Recipient.sent_at)).where(Recipient.sent_at <= now))


async def waiting_reason(session: AsyncSession, campaign: Campaign, now: datetime, s: OutreachSettings) -> str | None:
    """Why a running campaign cannot send right now, or None."""
    reason = window_reason(campaign, now)
    if reason:
        return reason
    day = now - timedelta(hours=24)
    if await delivered_since(session, day, now, campaign.id) >= daily_allowance(campaign, now):
        return f"Daily limit reached ({daily_allowance(campaign, now)} in 24 hours)"
    if await delivered_since(session, day, now) >= s.daily_limit:
        return f"Account limit reached ({s.daily_limit} emails in 24 hours across all campaigns)"
    return None


# --- composing --------------------------------------------------------------------


@dataclass
class Composed:
    subject: str
    body: str
    missing: list[str]


def compose(campaign: Campaign, recipient: Recipient, jobs: JobSettings) -> Composed:
    """The exact email for this recipient. Used by previews, test sends and the sender, so they always agree."""
    ctx = render.context(recipient.email, recipient.name, recipient.company, recipient.fields)
    subject = render.render(recipient.subject or campaign.subject_template, ctx, f"{recipient.id}s")
    body = render.render(recipient.body or campaign.body_template, ctx, f"{recipient.id}b")
    footer = render.render(campaign.footer, ctx, f"{recipient.id}f")
    text = body.text.rstrip()
    signature = jobs.signature.strip() or jobs.sender_name.strip()
    if campaign.append_signature and signature and text:
        text += f"\n\n{signature}"
    if footer.text.strip() and text:
        text += f"\n\n{footer.text.strip()}"
    missing = list(dict.fromkeys(subject.missing + body.missing + footer.missing))
    return Composed(subject=" ".join(subject.text.split()), body=text, missing=missing)


# --- contact history --------------------------------------------------------------


async def recent_contacts(
    session: AsyncSession, emails: list[str], days: int, exclude_recipient: int | None = None
) -> dict[str, str]:
    """For each address written to within `days`, a sentence saying when. Campaign mail and Jobs applications both count."""
    if days <= 0 or not emails:
        return {}
    since = utcnow() - timedelta(days=days)
    found: dict[str, str] = {}
    for i in range(0, len(emails), 1000):
        chunk = emails[i : i + 1000]
        query = (
            select(Recipient.email, func.max(Recipient.sent_at))
            .where(Recipient.email.in_(chunk), Recipient.sent_at >= since)
            .group_by(Recipient.email)
        )
        if exclude_recipient is not None:
            query = query.where(Recipient.id != exclude_recipient)
        for email, sent_at in (await session.execute(query)).all():
            found[email] = f"Already written to on {sent_at:%d %b %Y}"
        applications = (
            select(func.lower(JobApplication.to_email), func.max(JobApplication.sent_at))
            .where(
                JobApplication.status == ApplicationStatus.SENT,
                func.lower(JobApplication.to_email).in_(chunk),
                JobApplication.sent_at >= since,
            )
            .group_by(func.lower(JobApplication.to_email))
        )
        for email, sent_at in (await session.execute(applications)).all():
            found.setdefault(email, f"Already applied to on {sent_at:%d %b %Y} (Jobs)")
    return found


async def contacted_recently(session: AsyncSession, email: str, days: int, exclude_recipient: int | None = None) -> str | None:
    return (await recent_contacts(session, [email], days, exclude_recipient)).get(email)


async def is_suppressed(session: AsyncSession, email: str) -> bool:
    return await session.scalar(select(Suppression.id).where(Suppression.email == email)) is not None


# --- sending ----------------------------------------------------------------------


def _fail(recipient: Recipient, message: str) -> None:
    recipient.status, recipient.error, recipient.retry_at = RecipientStatus.FAILED, message, None


def _release(campaign: Campaign) -> None:
    """Nothing went out, so the next recipient does not have to wait for a pacing delay."""
    campaign.next_send_at = None


async def _pause(session: AsyncSession, campaign_ids: list[int], reason: str, notify) -> None:
    await session.execute(
        update(Campaign)
        .where(Campaign.id.in_(campaign_ids), Campaign.status == CampaignStatus.RUNNING)
        .values(status=CampaignStatus.PAUSED, pause_reason=reason[:300], next_send_at=None)
    )
    store.log_event(session, "outreach_paused", reason, "warning")
    if notify:
        await notify(f"Outreach paused: {reason}")


async def finish_if_done(session: AsyncSession, campaign: Campaign, now: datetime, notify=None) -> bool:
    open_left = await session.scalar(
        select(func.count())
        .select_from(Recipient)
        .where(Recipient.campaign_id == campaign.id, Recipient.status.in_([RecipientStatus.PENDING, RecipientStatus.SENDING]))
    )
    if open_left:
        return False
    campaign.status, campaign.finished_at, campaign.next_send_at = CampaignStatus.COMPLETED, now, None
    store.log_event(session, "outreach_completed", f"Campaign '{campaign.name}' finished")
    if notify:
        await notify(f"Outreach campaign '{campaign.name}' finished.")
    return True


async def _claim_recipient(session: AsyncSession, campaign: Campaign, now: datetime) -> Recipient | None:
    query = (
        select(Recipient)
        .where(
            Recipient.campaign_id == campaign.id,
            Recipient.status == RecipientStatus.PENDING,
            or_(Recipient.retry_at.is_(None), Recipient.retry_at <= now),
        )
        .order_by(Recipient.position, Recipient.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if campaign.mode == "ai":
        query = query.where(Recipient.body != "")  # the AI writes ahead of the sender
    recipient = await session.scalar(query)
    if recipient:
        recipient.status = RecipientStatus.SENDING
        recipient.attempts += 1
    return recipient


async def send_next(js, campaign_id: int, now: datetime) -> bool:
    """Send one email of this campaign if it is allowed to. True when an email went out."""
    async with js.sessions() as session:
        s = await outreach_settings(session)
        campaign = await session.get(Campaign, campaign_id, populate_existing=True)
        if campaign is None or campaign.status != CampaignStatus.RUNNING:
            return False
        if await waiting_reason(session, campaign, now, s):
            return False
        last = await last_send(session, now)
        if last and (now - last).total_seconds() < s.min_gap_seconds:
            return False

        # Reserve the next slot. Whoever wins this update sends; any other instance sees zero rows.
        delay = random.uniform(campaign.min_delay_seconds, campaign.max_delay_seconds)
        slot = await session.execute(
            update(Campaign)
            .where(
                Campaign.id == campaign_id,
                Campaign.status == CampaignStatus.RUNNING,
                or_(Campaign.next_send_at.is_(None), Campaign.next_send_at <= now),
            )
            .values(next_send_at=now + timedelta(seconds=delay))
        )
        if slot.rowcount != 1:
            await session.rollback()
            return False

        recipient = await _claim_recipient(session, campaign, now)
        if recipient is None:
            await session.refresh(campaign)
            if not await finish_if_done(session, campaign, now, js.notify):
                campaign.next_send_at = None  # nothing ready yet (retries waiting, AI still writing)
            await session.commit()
            return False
        await session.commit()

        return await _deliver(js, session, campaign, recipient, now)


async def _deliver(js, session: AsyncSession, campaign: Campaign, recipient: Recipient, now: datetime) -> bool:
    s = await outreach_settings(session)
    jobs = await jobs_settings(session)

    if await is_suppressed(session, recipient.email):
        recipient.status, recipient.error = RecipientStatus.SKIPPED, "On the do-not-contact list"
        _release(campaign)
        await session.commit()
        return False
    if not recipient.allow_recent:
        reason = await contacted_recently(session, recipient.email, s.skip_recent_days, exclude_recipient=recipient.id)
        if reason:
            recipient.status, recipient.error = RecipientStatus.SKIPPED, reason
            _release(campaign)
            await session.commit()
            return False

    composed = compose(campaign, recipient, jobs)
    problem = None
    if composed.missing:
        problem = "Missing value for: " + ", ".join(composed.missing) + ". Fill it in and retry."
    elif not composed.subject:
        problem = "No subject"
    elif not composed.body.strip():
        problem = "No message body"
    if problem:
        _fail(recipient, problem)
        _release(campaign)
        await session.commit()
        return False

    account = await store.get_config(session, GMAIL_KEY)
    if not account:
        recipient.status, recipient.attempts = RecipientStatus.PENDING, recipient.attempts - 1
        await _pause(session, [campaign.id], "Gmail is not connected", js.notify)
        await session.commit()
        return False

    attachment = None
    if campaign.resume_id and campaign.resume:
        data = await session.scalar(select(JobResume.data).where(JobResume.id == campaign.resume_id))
        attachment = Attachment(campaign.resume.filename, campaign.resume.content_type, data)
    message = gmail_lib.build_message(
        sender_email=account["email"],
        sender_name=jobs.sender_name,
        to=recipient.email,
        cc=[],
        subject=composed.subject,
        body=composed.body,
        attachment=attachment,
    )
    try:
        result = await js.gmail.send(gmail_lib.decrypt(account["refresh_token"], get_env().secret_key), message)
    except GmailError as e:
        await _handle_send_error(js, session, campaign, recipient, e, now)
        await session.commit()
        return False

    recipient.status, recipient.error, recipient.retry_at = RecipientStatus.SENT, None, None
    recipient.sent_at = now
    recipient.gmail_message_id, recipient.gmail_thread_id = result.get("id"), result.get("threadId")
    store.log_event(session, "outreach_sent", f"Sent to {recipient.email} ({campaign.name})")
    await session.commit()
    return True


async def _handle_send_error(js, session: AsyncSession, campaign: Campaign, recipient: Recipient, e: GmailError, now: datetime) -> None:
    text = str(e)
    code = e.status_code
    store.log_event(session, "outreach_send_failed", f"{recipient.email}: {text}", "error")
    if e.outcome_unknown:
        # Gmail may have sent it. Retrying could email the person twice, so a human decides.
        _fail(recipient, text)
        return
    if code == 401 or (code == 400 and ("revoked" in text or "expired" in text)):
        recipient.status, recipient.attempts = RecipientStatus.PENDING, recipient.attempts - 1
        running = list(await session.scalars(select(Campaign.id).where(Campaign.status == CampaignStatus.RUNNING)))
        await _pause(session, running, "Gmail access was revoked. Connect Gmail again, then resume.", js.notify)
        return
    if code == 429 or (code == 403 and any(w in text.lower() for w in ("rate", "quota", "limit"))):
        recipient.status, recipient.attempts, recipient.error = RecipientStatus.PENDING, recipient.attempts - 1, text
        await _pause(session, [campaign.id], f"Gmail is limiting this account. {text}", js.notify)
        return
    if (code is None or code >= 500) and recipient.attempts < MAX_ATTEMPTS:
        recipient.status, recipient.error = RecipientStatus.PENDING, text
        recipient.retry_at = now + timedelta(minutes=5 * recipient.attempts)
        return
    _fail(recipient, text)


# --- AI writing ahead of the sender -----------------------------------------------


async def generate_ahead(js, now: datetime) -> None:
    """For running AI campaigns, write the next few emails so the sender always has one ready."""
    async with js.sessions() as session:
        s = await outreach_settings(session)
        jobs = await jobs_settings(session)
        campaigns = list(
            await session.scalars(
                select(Campaign).where(Campaign.status == CampaignStatus.RUNNING, Campaign.mode == "ai").order_by(Campaign.id)
            )
        )
        if not campaigns:
            return
        problem = js.llm.model_problem(s.model)
        if problem:
            await _pause(session, [c.id for c in campaigns], f"The AI model is unavailable: {problem}", js.notify)
            await session.commit()
            return
        jobs_for = []
        for campaign in campaigns:
            rows = await session.scalars(
                select(Recipient)
                .where(
                    Recipient.campaign_id == campaign.id,
                    Recipient.status == RecipientStatus.PENDING,
                    Recipient.body == "",
                    or_(Recipient.retry_at.is_(None), Recipient.retry_at <= now),
                )
                .order_by(Recipient.position, Recipient.id)
                .limit(GENERATE_PER_TICK)
            )
            jobs_for += [(campaign.ai_brief, r.id, r.email, r.name, r.company, r.fields) for r in rows]

    for brief, recipient_id, email, name, company, fields in jobs_for:
        ctx = render.context(email, name, company, fields)
        try:
            subject, body = await writer.write_for_recipient(js.llm, s.model, brief, ctx, jobs.sender_name)
            error = None
        except LLMError as e:
            subject = body = ""
            error = f"The AI could not write this email: {e}"
        async with js.sessions() as session:
            recipient = await session.get(Recipient, recipient_id, populate_existing=True)
            if recipient is None or recipient.status != RecipientStatus.PENDING or recipient.body:
                continue  # edited or sent by someone else in the meantime
            if error:
                recipient.attempts += 1
                recipient.error = error
                if recipient.attempts >= MAX_ATTEMPTS:
                    _fail(recipient, error)
                else:
                    recipient.retry_at = now + timedelta(minutes=5 * recipient.attempts)
            else:
                recipient.subject, recipient.body, recipient.error = subject, body, None
            await session.commit()


# --- replies and bounces ----------------------------------------------------------


def classify_thread(messages: list[dict], my_email: str, sent_id: str | None) -> str | None:
    """RecipientStatus.BOUNCED or REPLIED when something other than our own message is in the thread."""
    outcome = None
    for message in messages:
        if message.get("id") == sent_id:
            continue
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        sender = headers.get("from", "").lower()
        if "mailer-daemon" in sender or "postmaster" in sender:
            return RecipientStatus.BOUNCED
        if my_email.lower() in sender:
            continue  # our own follow-up
        if headers.get("auto-submitted", "no").strip().lower() not in ("", "no"):
            continue  # out-of-office and other automatic answers are not a reply
        outcome = RecipientStatus.REPLIED
    return outcome


async def check_replies(js, now: datetime) -> None:
    async with js.sessions() as session:
        account = await store.get_config(session, GMAIL_KEY)
        if not account:
            return
        s = await outreach_settings(session)
        recent = now - timedelta(days=1)
        rows = list(
            await session.scalars(
                select(Recipient)
                .where(
                    Recipient.status == RecipientStatus.SENT,
                    Recipient.gmail_thread_id.is_not(None),
                    Recipient.sent_at > now - REPLY_WINDOW,
                    # Fresh sends are looked at often, older ones every few hours.
                    or_(
                        Recipient.checked_at.is_(None),
                        (Recipient.sent_at > recent) & (Recipient.checked_at < now - timedelta(minutes=15)),
                        Recipient.checked_at < now - timedelta(hours=3),
                    ),
                )
                .order_by(Recipient.checked_at.asc().nulls_first())
                .limit(CHECKS_PER_TICK)
            )
        )
        if not rows:
            return
        try:
            refresh = gmail_lib.decrypt(account["refresh_token"], get_env().secret_key)
        except GmailError:
            return
        touched: set[int] = set()
        for recipient in rows:
            recipient.checked_at = now
            try:
                messages = await js.gmail.thread(refresh, recipient.gmail_thread_id)
            except GmailError as e:
                logger.warning("Could not read thread %s: %s", recipient.gmail_thread_id, e)
                continue
            outcome = classify_thread(messages, account["email"], recipient.gmail_message_id)
            if outcome == RecipientStatus.BOUNCED:
                recipient.status, recipient.error = RecipientStatus.BOUNCED, "Gmail could not deliver this email"
                if not await is_suppressed(session, recipient.email):
                    session.add(Suppression(email=recipient.email, reason="Bounced"))
                touched.add(recipient.campaign_id)
            elif outcome == RecipientStatus.REPLIED:
                recipient.status = RecipientStatus.REPLIED
                store.log_event(session, "outreach_reply", f"{recipient.email} replied")
        await session.flush()
        for campaign_id in touched:
            await _pause_on_bounces(js, session, campaign_id, s)
        await session.commit()


async def _pause_on_bounces(js, session: AsyncSession, campaign_id: int, s: OutreachSettings) -> None:
    counts = dict(
        (await session.execute(select(Recipient.status, func.count()).where(Recipient.campaign_id == campaign_id).group_by(Recipient.status))).all()
    )
    delivered = sum(counts.get(status, 0) for status in RecipientStatus.DELIVERED)
    bounced = counts.get(RecipientStatus.BOUNCED, 0)
    if delivered >= MIN_SENT_FOR_BOUNCE_RATE and bounced * 100 >= s.bounce_pause_percent * delivered:
        await _pause(
            session,
            [campaign_id],
            f"{bounced} of {delivered} emails bounced. Check the list before continuing, bad addresses hurt your Gmail reputation.",
            js.notify,
        )


# --- the loop ---------------------------------------------------------------------


async def recover_stuck(js, now: datetime) -> None:
    async with js.sessions() as session:
        stuck = await session.execute(
            update(Recipient)
            .where(Recipient.status == RecipientStatus.SENDING, Recipient.updated_at < now - STUCK_AFTER)
            .values(
                status=RecipientStatus.FAILED,
                error="The server stopped while sending this. Check Gmail's Sent folder before retrying.",
            )
        )
        if stuck.rowcount:
            store.log_event(session, "outreach_recovered", f"{stuck.rowcount} email(s) were left half-sent", "warning")
        await session.commit()


async def tick(js, now: datetime | None = None) -> int:
    """One pass of the sender. Returns how many emails went out (0 or 1)."""
    now = now or utcnow()
    await recover_stuck(js, now)
    async with js.sessions() as session:
        running = list(await session.scalars(select(Campaign.id).where(Campaign.status == CampaignStatus.RUNNING).order_by(Campaign.id)))
    sent = 0
    for campaign_id in running:
        if await send_next(js, campaign_id, now):
            sent = 1
            break  # one email per pass; the account-wide gap also forbids a second
    await generate_ahead(js, now)
    await check_replies(js, now)
    return sent
