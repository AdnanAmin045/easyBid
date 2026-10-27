"""Follow-ups for sent job applications, and reply tracking for them.

Runs next to the outreach sender (see app.main) and obeys the same account-wide limits and gap, because both
send from the same Gmail. An application is followed up only while nobody has answered: the conversation is
read before every follow-up, and if Gmail cannot be read nothing is sent.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select, update

from app.jobs import accounts
from app.jobs import gmail as gmail_lib
from app.jobs.mailbox import open_mailbox
from app.jobs.gmail import GmailError
from app.jobs.models import ApplicationStatus, GmailAccount, JobApplication, JobResume
from app.jobs.schemas import JobSettings
from app.models import utcnow
from app.outreach import engine, render
from app.outreach.models import RecipientStatus, Suppression
from app.services import store

logger = logging.getLogger("easybid")

CLAIM_STALE = timedelta(minutes=10)  # a follow-up claimed this long ago was interrupted, and is skipped, never repeated
MAX_ERRORS = 3
WATCH_DEFAULT = timedelta(days=30)  # replies are looked for this long after sending, longer while follow-ups remain
WATCH_FOLLOWUPS = timedelta(days=75)
CHECKS_PER_TICK = 5


@dataclass
class Composed:
    subject: str
    body: str
    missing: list[str]


def compose(application: JobApplication, step: int, jobs: JobSettings) -> Composed:
    """Follow-up number `step` (0 based), in the same conversation as the application."""
    plan = application.followups[step]
    name = str((application.details or {}).get("recipient_name") or "")
    ctx = render.context(application.to_email, name, application.company, {"role": application.role, "location": application.location})
    body = render.render(plan["body"], ctx, f"j{application.id}{step}b")
    own = render.render(plan.get("subject", ""), ctx, f"j{application.id}{step}s")
    first = application.sent_subject or application.subject
    subject = own.text.strip() or (first if first.lower().startswith("re:") else f"Re: {first}")
    text = body.text.rstrip()
    text = engine.with_signature(text, jobs)
    return Composed(" ".join(subject.split()), text, list(dict.fromkeys(body.missing + own.missing)))


def remaining(application: JobApplication) -> int:
    return max(len(application.followups or []) - application.followups_sent, 0)


async def _recover(js, now: datetime) -> None:
    async with js.sessions() as session:
        done = await session.execute(
            update(JobApplication)
            .where(JobApplication.followup_claim_at < now - CLAIM_STALE)
            .values(
                followup_claim_at=None,
                followups_sent=JobApplication.followups_sent + 1,
                followup_note="A follow-up was interrupted by a server stop and skipped. Check Gmail's Sent folder.",
            )
        )
        if done.rowcount:
            store.log_event(session, "jobs_followup_recovered", f"{done.rowcount} follow-up(s) were interrupted", "warning")
        await session.commit()


async def _mark_outcome(session, application: JobApplication, outcome: str) -> None:
    if outcome == RecipientStatus.FAILED:
        # Gmail could not send as the address: the application never left, and nobody has answered or bounced.
        application.status = ApplicationStatus.FAILED
        application.error = engine.SENDAS_FAILED.format(address="this address")
        application.followups_sent = len(application.followups or [])
        store.log_event(session, "jobs_send_failed", f"{application.to_email}: {application.error}", "error")
        return
    application.outcome = outcome
    if outcome == RecipientStatus.BOUNCED:
        application.followup_note = "Gmail could not deliver this email"
        if not await engine.is_suppressed(session, application.to_email):
            session.add(Suppression(email=application.to_email, reason="Bounced"))
    else:
        store.log_event(session, "jobs_reply", f"{application.to_email} replied")


async def send_due(js, now: datetime) -> int:
    """Send at most one due follow-up. Returns 1 when an email went out."""
    async with js.sessions() as session:
        if not await accounts.any_connected(session):
            return 0
        s = await engine.outreach_settings(session)

        rows = await session.scalars(
            select(JobApplication)
            .where(
                JobApplication.status == ApplicationStatus.SENT,
                JobApplication.outcome == "",
                JobApplication.followup_claim_at.is_(None),
                JobApplication.gmail_thread_id.is_not(None),
                JobApplication.gmail_account_id.is_not(None),
                JobApplication.last_contact_at.is_not(None),
                func.jsonb_array_length(JobApplication.followups) > JobApplication.followups_sent,
                or_(JobApplication.followup_retry_at.is_(None), JobApplication.followup_retry_at <= now),
            )
            .order_by(JobApplication.last_contact_at)
            .limit(50)
            .with_for_update(skip_locked=True)
        )
        application = None
        for candidate in rows:
            if candidate.last_contact_at + timedelta(days=candidate.followups[candidate.followups_sent]["days"]) > now:
                continue
            # The follow-up goes from the Gmail the application went from, under that Gmail's own limits.
            if await engine.account_reason(session, candidate.gmail_account_id, now, s):
                continue
            application = candidate
            break
        if application is None:
            return 0
        account = await accounts.resolve(session, application.gmail_account_id)
        if account is None:
            return 0
        step = application.followups_sent
        application.followup_claim_at = now
        await session.commit()
        return await _deliver(js, session, application, step, account, now)


async def _deliver(js, session, application: JobApplication, step: int, account: GmailAccount, now: datetime) -> bool:
    def settle(note: str | None = None, skip: bool = False, retry_in: timedelta | None = None) -> bool:
        application.followup_claim_at = None
        application.followup_note = note
        application.followup_retry_at = now + retry_in if retry_in else None
        if skip:
            application.followups_sent, application.followup_errors = step + 1, 0
        return False

    if await engine.is_suppressed(session, application.to_email):
        application.followups_sent = len(application.followups)
        settle("On the do-not-contact list, no follow-ups")
        await session.commit()
        return False
    if await engine.replied_before(session, [application.to_email.lower()]):
        # They answered something else of ours (a campaign, or another application): no more follow-ups.
        settle(application.followup_note)
        await _mark_outcome(session, application, RecipientStatus.REPLIED)
        await session.commit()
        return False
    try:
        mailbox = open_mailbox(js, account)
        # Never follow up blind: look at the conversation, and at anything else they have written, first.
        outcome = await engine.thread_outcome(
            mailbox,
            account.email,
            application.gmail_thread_id,
            application.gmail_message_id,
            application.to_email,
            application.sent_at,
        )
    except GmailError as e:
        settle(f"Could not check for a reply, will try again: {e}", retry_in=timedelta(minutes=15))
        await session.commit()
        return False
    if outcome:
        settle(application.followup_note)
        await _mark_outcome(session, application, outcome)
        await session.commit()
        return False

    jobs = accounts.identity(await engine.jobs_settings(session), account)
    composed = compose(application, step, jobs)
    if composed.missing or not composed.body.strip():
        settle(f"Follow-up {step + 1} skipped: missing value for {', '.join(composed.missing) or 'the message'}", skip=True)
        await session.commit()
        return False

    attachment = None
    if application.followups[step].get("attach_resume") and application.resume_id and application.resume:
        data = await session.scalar(select(JobResume.data).where(JobResume.id == application.resume_id))
        attachment = gmail_lib.Attachment(application.resume.filename, application.resume.content_type, data)
    message = gmail_lib.build_message(
        sender_email=account.email,
        sender_name=jobs.sender_name,
        to=application.to_email,
        cc=[],
        subject=composed.subject,
        body=composed.body,
        attachment=attachment,
        in_reply_to=application.rfc_id or None,
    )
    try:
        await mailbox.send(message, thread_id=application.gmail_thread_id)
    except GmailError as e:
        text, code = str(e), e.status_code
        store.log_event(session, "jobs_followup_failed", f"{application.to_email} (follow-up {step + 1}): {text}", "error")
        if e.outcome_unknown:
            settle(f"Follow-up {step + 1}: {text}", skip=True)  # it may have gone, so it is not repeated
        elif code == 401 or code == 429 or (code == 403 and any(w in text.lower() for w in ("rate", "quota", "limit"))) or (
            code == 400 and ("revoked" in text or "expired" in text)
        ):
            settle(f"Gmail refused: {text}", retry_in=timedelta(hours=1))
        elif e.unreachable:
            settle(f"{text} Will try again.", retry_in=timedelta(hours=1))  # not counted: nothing was sent
        elif code is None or code >= 500:
            application.followup_errors += 1
            if application.followup_errors >= MAX_ERRORS:
                settle(f"Follow-up {step + 1} failed: {text}", skip=True)
            else:
                settle(text, retry_in=timedelta(minutes=5 * application.followup_errors))
        else:
            settle(f"Follow-up {step + 1} refused: {text}", skip=True)
        await session.commit()
        return False

    settle(None)
    application.followups_sent, application.followup_errors = step + 1, 0
    application.last_contact_at = now
    application.rfc_id = str(message["Message-ID"])
    store.log_event(session, "jobs_followup", f"Follow-up {step + 1} sent to {application.to_email}")
    await session.commit()
    return True


async def check_replies(js, now: datetime) -> None:
    """Look at a few sent applications for an answer, so the list shows who replied or bounced."""
    async with js.sessions() as session:
        if not await accounts.any_connected(session):
            return
        left = func.jsonb_array_length(JobApplication.followups) > JobApplication.followups_sent
        rows = list(
            await session.scalars(
                select(JobApplication)
                .where(
                    JobApplication.status == ApplicationStatus.SENT,
                    JobApplication.outcome == "",
                    JobApplication.gmail_thread_id.is_not(None),
                    JobApplication.gmail_account_id.is_not(None),
                    or_(
                        (JobApplication.sent_at > now - WATCH_DEFAULT),
                        left & (JobApplication.sent_at > now - WATCH_FOLLOWUPS),
                    ),
                    or_(
                        JobApplication.checked_at.is_(None),
                        (JobApplication.sent_at > now - timedelta(minutes=30)) & (JobApplication.checked_at < now - timedelta(minutes=2)),
                        (JobApplication.sent_at > now - timedelta(days=1)) & (JobApplication.checked_at < now - timedelta(minutes=15)),
                        JobApplication.checked_at < now - timedelta(hours=3),
                    ),
                )
                .order_by(JobApplication.checked_at.asc().nulls_first())
                .limit(CHECKS_PER_TICK)
            )
        )
        if not rows:
            return
        found = await session.scalars(select(GmailAccount).where(GmailAccount.id.in_({r.gmail_account_id for r in rows})).execution_options(populate_existing=True))
        mailboxes = {a.id: a for a in await accounts.with_parents(session, list(found))}
        for application in rows:
            application.checked_at = now
            account = mailboxes.get(application.gmail_account_id)
            if account is None:
                continue  # its Gmail was disconnected, there is nothing left to read
            try:
                mailbox = open_mailbox(js, account)
                messages = await mailbox.thread(application.gmail_thread_id)
            except GmailError as e:
                logger.warning("Could not read thread %s: %s", application.gmail_thread_id, e)
                continue
            outcome = engine.classify_thread(messages, account.email, application.gmail_message_id)
            if outcome is None:
                try:
                    if await mailbox.answered_by(application.to_email, application.sent_at):
                        outcome = RecipientStatus.REPLIED
                except GmailError as e:
                    logger.warning("Could not look for answers from %s: %s", application.to_email, e)
                    continue
            if outcome:
                await _mark_outcome(session, application, outcome)
        await session.commit()


async def tick(js, now: datetime | None = None) -> int:
    now = now or utcnow()
    await _recover(js, now)
    sent = await send_due(js, now)
    await check_replies(js, now)
    return sent
