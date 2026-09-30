"""One-off: copy the data from the old local SQLite file into the Postgres database in DATABASE_URL.

Usage (from the backend folder, after `alembic upgrade head`):

    python -m scripts.import_sqlite easybid.db

Rows that already exist in Postgres are left untouched, so it is safe to run twice.
"""

import asyncio
import json
import sqlite3
import sys
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, text
from sqlalchemy.dialects.postgresql import JSONB, insert

from app.db import engine
from app.models import AppConfig, EventLog, ProfileItem, Project, Prompt, Proposal

# Parents before children, so foreign keys resolve.
MODELS = [AppConfig, Prompt, ProfileItem, Project, Proposal, EventLog]
SERIAL_TABLES = ["prompts", "profile_items", "proposals", "event_logs"]


def convert(column, value):
    if value is None:
        return None
    if isinstance(column.type, JSONB) and isinstance(value, str):
        return json.loads(value)
    if isinstance(column.type, DateTime):
        parsed = datetime.fromisoformat(value)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    if isinstance(column.type, Boolean):
        return bool(value)
    return value


async def main(path: str) -> None:
    source = sqlite3.connect(path)
    source.row_factory = sqlite3.Row

    async with engine.begin() as conn:
        for model in MODELS:
            table = model.__table__
            available = {row["name"] for row in source.execute(f"PRAGMA table_info({table.name})")}
            columns = [c for c in table.columns if c.name in available]
            rows = [
                {c.name: convert(c, row[c.name]) for c in columns}
                for row in source.execute(f"SELECT * FROM {table.name}")
            ]
            if rows:
                await conn.execute(insert(table).on_conflict_do_nothing(), rows)
            print(f"{table.name}: {len(rows)} rows")

        # Explicit ids were inserted, so move each id sequence past them.
        for name in SERIAL_TABLES:
            await conn.execute(
                text(f"SELECT setval(pg_get_serial_sequence('{name}', 'id'), COALESCE(MAX(id), 0) + 1, false) FROM {name}")
            )
    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Usage: python -m scripts.import_sqlite <path-to-sqlite-file>")
    asyncio.run(main(sys.argv[1]))
