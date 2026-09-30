"""Small helpers over the app_config and event_logs tables."""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppConfig, EventLog
from app.schemas import AppSettings

logger = logging.getLogger("easybid")

SETTINGS = "settings"
ACCOUNT = "account"
RUNTIME = "runtime"
RESTRICTIONS = "restrictions"


async def get_config(session: AsyncSession, key: str) -> dict:
    row = await session.get(AppConfig, key)
    return dict(row.value) if row else {}


async def set_config(session: AsyncSession, key: str, value: dict) -> None:
    row = await session.get(AppConfig, key)
    if row:
        row.value = value
    else:
        session.add(AppConfig(key=key, value=value))


async def get_settings(session: AsyncSession) -> AppSettings:
    return AppSettings(**await get_config(session, SETTINGS))


async def save_settings(session: AsyncSession, settings: AppSettings) -> None:
    await set_config(session, SETTINGS, settings.model_dump())


def log_event(session: AsyncSession, event: str, message: str, level: str = "info", project_id: int | None = None):
    logger.log(logging.getLevelName(level.upper()), "%s: %s", event, message)
    session.add(EventLog(event=event, message=message, level=level, project_id=project_id))
