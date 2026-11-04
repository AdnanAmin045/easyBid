"""The daily routine: write each profile's post at the generation time, publish approved posts when they are due.

Safe next to another instance: a post is claimed with a compare-and-set on its status, and the one-post-per-day
rule is a unique constraint in the database.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_env
from app.jobs import gmail as crypto
from app.jobs.gmail import GmailError
from app.linkedin import content
from app.linkedin.client import LinkedInClient, LinkedInError
from app.linkedin.models import COMPANY, PERSONAL, TARGETS, LinkedInAccount, LinkedInConfig, LinkedInPost, PostStatus
from app.linkedin.poster import Brand, render_poster
from app.linkedin.schemas import LinkedInSettings
from app.models import utcnow
from app.services.llm import LLM, LLMError
from app.services.notifier import Notifier

logger = logging.getLogger("easybid")

# A failed draft is tried again this often, so a quota that resets does not need anyone to notice.
RETRY_AFTER = timedelta(minutes=20)
EXPIRY_WARNING = timedelta(days=7)


@dataclass
class LinkedInServices:
    sessions: async_sessionmaker[AsyncSession]
    llm: LLM
    client: LinkedInClient
    notifier: Notifier
    # target -> when generation last failed, in this process only
    failed_at: dict[str, datetime] | None = None


async def get_config(session: AsyncSession) -> tuple[LinkedInSettings, LinkedInConfig]:
    row = await session.get(LinkedInConfig, 1)
    if row is None:
        row = LinkedInConfig(id=1, data={})
        session.add(row)
        await session.flush()
    return LinkedInSettings.model_validate(row.data or {}), row


DEFAULT_LOGO = Path(__file__).resolve().parents[2] / "assets" / "codevryn-logo.png"


def brand_of(s: LinkedInSettings, row: LinkedInConfig, target: str = COMPANY, person: str = "") -> Brand:
    """How a poster looks. The company's: its logo (the one uploaded in the settings, else the Codevryn logo that ships with the
    server), its website and colours. The person's: no logo and no website, their own colours, round avatar, name and what they do."""
    if target == PERSONAL:
        return Brand(
            name=(s.personal_name or person).strip(), website="", primary=s.personal_primary, accent=s.personal_accent, logo=None,
            style="personal", tagline=s.personal_title,
        )
    logo = row.logo or (DEFAULT_LOGO.read_bytes() if DEFAULT_LOGO.exists() else None)
    return Brand(name=s.brand_name, website=s.website, primary=s.brand_primary, accent=s.brand_accent, logo=logo)


async def brand_for(session: AsyncSession, target: str, s: LinkedInSettings, row: LinkedInConfig) -> Brand:
    account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == PERSONAL)) if target == PERSONAL else None
    return brand_of(s, row, target, account.name if account else "")


def local_now(s: LinkedInSettings) -> datetime:
    return utcnow().astimezone(ZoneInfo(s.timezone))


def at_local(day: date, clock: str, s: LinkedInSettings) -> datetime:
    h, m = clock.split(":")
    return datetime(day.year, day.month, day.day, int(h), int(m), tzinfo=ZoneInfo(s.timezone))


def author_for(target: str, account: LinkedInAccount | None, s: LinkedInSettings) -> str:
    if target == COMPANY:
        return f"urn:li:organization:{s.company_page_id}" if s.company_page_id else ""
    return account.author_urn if account else ""


def token_of(account: LinkedInAccount) -> str:
    try:
        return crypto.decrypt(account.access_token, get_env().secret_key)
    except GmailError:
        raise LinkedInError("The saved LinkedIn login cannot be read (SECRET_KEY changed?). Connect the account again.") from None


def usable(account: LinkedInAccount | None) -> bool:
    return bool(account and account.access_token and (account.expires_at is None or account.expires_at > utcnow()))


async def create_draft(
    svc: LinkedInServices, session: AsyncSession, target: str, day: date, s: LinkedInSettings, row: LinkedInConfig, brief: str = "", slot: int | None = None,
) -> LinkedInPost:
    """Write one post for `target` and save it. The day's first post goes out at the usual time, later ones soon after approval."""
    ts = s.for_target(target)
    brand = await brand_for(session, target, s, row)
    made = await content.generate_post(svc.llm, session, target, s, day, brief, brand)
    if slot is None:
        taken = set(await session.scalars(select(LinkedInPost.slot).where(LinkedInPost.target == target, LinkedInPost.post_date == day)))
        slot = next(i for i in range(100) if i not in taken)
    poster = render_poster(made.poster_spec, brand) if made.poster_spec else None
    account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == target))
    when = at_local(day, ts.post_time, s)
    if slot > 0 or when < utcnow():
        when = utcnow() + timedelta(minutes=10)
    ready = ts.auto_approve and usable(account) and bool(author_for(target, account, s))
    post = LinkedInPost(
        target=target, post_date=day, slot=slot, pillar=made.pillar, topic=made.topic, text=made.text, first_comment=ts.first_comment,
        poster_spec=made.poster_spec, poster=poster, alt_text=made.alt_text, signals=made.signals,
        status=PostStatus.APPROVED if ready else PostStatus.DRAFT, scheduled_for=when,
    )
    session.add(post)
    await session.flush()
    return post


def _label(target: str, s: LinkedInSettings) -> str:
    return "personal profile" if target == PERSONAL else f"{s.brand_name} page"


async def generate_due(svc: LinkedInServices) -> None:
    """Write today's post for each enabled profile that has none yet, once the generation time has passed."""
    failed = svc.failed_at = svc.failed_at or {}
    async with svc.sessions() as session:
        s, row = await get_config(session)
        await session.commit()
    now = local_now(s)
    if now < at_local(now.date(), s.generate_time, s):
        return
    for target in TARGETS:
        ts = s.for_target(target)
        if not ts.enabled or now.weekday() not in ts.days:
            continue
        if (last := failed.get(target)) and utcnow() - last < RETRY_AFTER:
            continue
        async with svc.sessions() as session:
            account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == target))
            if not usable(account) and not s.draft_without_connection:
                continue
            exists = await session.scalar(
                select(LinkedInPost.id).where(LinkedInPost.target == target, LinkedInPost.post_date == now.date()).limit(1)
            )
            if exists:
                continue
            try:
                post = await create_draft(svc, session, target, now.date(), s, row, slot=0)
                await session.commit()
            except IntegrityError:
                await session.rollback()  # another instance wrote it first
                continue
            except LLMError as e:
                await session.rollback()
                failed[target] = utcnow()
                logger.warning("LinkedIn: could not write the %s post: %s", _label(target, s), e)
                continue
        failed.pop(target, None)
        state = "will be posted" if post.status == PostStatus.APPROVED else "is waiting for your approval"
        await svc.notifier.send(f"LinkedIn {_label(target, s)}: today's post {state}.\n\n{post.text[:400]}")


async def publish(svc: LinkedInServices, post_id: int) -> LinkedInPost:
    """Publish one approved post. It is claimed first, so two runs never post it twice."""
    async with svc.sessions() as session:
        claimed = await session.execute(
            update(LinkedInPost).where(LinkedInPost.id == post_id, LinkedInPost.status == PostStatus.APPROVED).values(status=PostStatus.POSTING)
        )
        await session.commit()
        if claimed.rowcount != 1:
            raise LinkedInError("This post is not approved, or is already being posted")
        post = await session.get(LinkedInPost, post_id)
        s, _ = await get_config(session)
        account = await session.scalar(select(LinkedInAccount).where(LinkedInAccount.target == post.target))
        try:
            if not usable(account):
                raise LinkedInError("The LinkedIn account is not connected, or its login has expired. Connect it again.")
            author = author_for(post.target, account, s)
            if not author:
                raise LinkedInError("The company page id is not set. Add it in the LinkedIn settings.")
            token = token_of(account)
            image = await svc.client.upload_image(token, author, post.poster) if post.poster else None
            urn = await svc.client.publish(token, author, post.text, s.mentions, image, post.alt_text)
            post.status, post.linkedin_urn, post.posted_at, post.error = PostStatus.POSTED, urn, utcnow(), ""
            await session.commit()
        except LinkedInError as e:
            # An unknown outcome is not retried: the post may be live already.
            post.status, post.error = PostStatus.FAILED, str(e)
            await session.commit()
            logger.warning("LinkedIn: posting %s failed: %s", post.id, e)
            await svc.notifier.send(f"LinkedIn post failed ({_label(post.target, s)}): {e}")
            return post
        if post.first_comment.strip() and urn:
            try:
                await svc.client.comment(token, author, urn, post.first_comment.strip())
            except LinkedInError as e:
                logger.warning("LinkedIn: first comment on %s failed: %s", urn, e)
                post.error = f"Posted, but the first comment failed: {e}"
                await session.commit()
        await svc.notifier.send(f"LinkedIn: posted to the {_label(post.target, s)}.\nhttps://www.linkedin.com/feed/update/{urn}/")
        return post


async def publish_due(svc: LinkedInServices) -> None:
    async with svc.sessions() as session:
        ids = list(
            await session.scalars(
                select(LinkedInPost.id).where(LinkedInPost.status == PostStatus.APPROVED, LinkedInPost.scheduled_for <= utcnow()).order_by(LinkedInPost.scheduled_for).limit(5)
            )
        )
    for post_id in ids:
        try:
            await publish(svc, post_id)
        except LinkedInError:
            pass  # someone else claimed it


async def warn_expiring(svc: LinkedInServices) -> None:
    """A LinkedIn login lasts 60 days and cannot be renewed in the background: say so a week ahead."""
    async with svc.sessions() as session:
        for account in await session.scalars(select(LinkedInAccount).where(LinkedInAccount.expiry_warned.is_(False))):
            if account.expires_at and account.expires_at - utcnow() < EXPIRY_WARNING:
                account.expiry_warned = True
                left = max(0, (account.expires_at - utcnow()).days)
                await svc.notifier.send(f"LinkedIn login for the {account.target} account expires in {left} days. Open the LinkedIn page and press Connect again to keep posting.")
        await session.commit()


async def tick(svc: LinkedInServices) -> None:
    await generate_due(svc)
    await publish_due(svc)
    await warn_expiring(svc)
