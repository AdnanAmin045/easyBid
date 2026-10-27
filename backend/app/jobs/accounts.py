"""The Gmail accounts emails are sent from, shared by Jobs applications and outreach campaigns."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import GmailAccount
from app.jobs.schemas import JobSettings


async def with_parents(session: AsyncSession, found: list[GmailAccount]) -> list[GmailAccount]:
    """Refresh the Gmail behind each alias. After a commit it is stale, and sending needs its token."""
    for account in found:
        if account.parent_id:
            # A plain attribute, not the ORM relationship: lazy loading does not work in async code.
            account.gmail_owner = await session.get(GmailAccount, account.parent_id, populate_existing=True)
    return found


async def default_account(session: AsyncSession) -> GmailAccount | None:
    query = select(GmailAccount).order_by(GmailAccount.is_default.desc(), GmailAccount.id).limit(1)
    account = await session.scalar(query.execution_options(populate_existing=True))
    return (await with_parents(session, [account]))[0] if account else None


async def resolve(session: AsyncSession, account_id: int | None) -> GmailAccount | None:
    """The chosen account, or the default one when none was chosen. None when the chosen one was disconnected."""
    if account_id is None:
        return await default_account(session)
    account = await session.get(GmailAccount, account_id, populate_existing=True)
    return (await with_parents(session, [account]))[0] if account else None


async def any_connected(session: AsyncSession) -> bool:
    return await session.scalar(select(GmailAccount.id).limit(1)) is not None


async def family(session: AsyncSession, account_id: int) -> list[int]:
    """The account and everything that shares its mailbox: a Gmail and its "send as" aliases count as one for limits."""
    account = await session.get(GmailAccount, account_id)
    root = (account.parent_id or account.id) if account else account_id
    children = await session.scalars(select(GmailAccount.id).where(GmailAccount.parent_id == root))
    return [root, *children]


def root_id(account: GmailAccount) -> int:
    return account.parent_id or account.id


def identity(jobs: JobSettings, account: GmailAccount) -> JobSettings:
    """The sender name and signature to use for this account: its own, or the ones in the Jobs settings."""
    return jobs.model_copy(
        update={
            "sender_name": account.sender_name.strip() or jobs.sender_name,
            "signature": account.signature.strip() or jobs.signature,
        }
    )
