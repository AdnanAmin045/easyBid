"""The Gmail accounts emails are sent from, shared by Jobs applications and outreach campaigns."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import GmailAccount
from app.jobs.schemas import JobSettings


async def default_account(session: AsyncSession) -> GmailAccount | None:
    return await session.scalar(select(GmailAccount).order_by(GmailAccount.is_default.desc(), GmailAccount.id).limit(1))


async def resolve(session: AsyncSession, account_id: int | None) -> GmailAccount | None:
    """The chosen account, or the default one when none was chosen. None when the chosen one was disconnected."""
    if account_id is None:
        return await default_account(session)
    return await session.get(GmailAccount, account_id)


async def any_connected(session: AsyncSession) -> bool:
    return await session.scalar(select(GmailAccount.id).limit(1)) is not None


def identity(jobs: JobSettings, account: GmailAccount) -> JobSettings:
    """The sender name and signature to use for this account: its own, or the ones in the Jobs settings."""
    return jobs.model_copy(
        update={
            "sender_name": account.sender_name.strip() or jobs.sender_name,
            "signature": account.signature.strip() or jobs.signature,
        }
    )
