from collections.abc import AsyncIterator
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_env

LOCAL_HOSTS = {"localhost", "127.0.0.1"}


def build_engine(database_url: str, **engine_kwargs) -> AsyncEngine:
    """Async engine for Supabase Postgres (or any Postgres)."""
    if not database_url:
        raise RuntimeError("DATABASE_URL is not set. Use the Supabase session pooler connection string.")
    url = make_url(database_url)
    if not url.drivername.startswith("postgres"):
        raise RuntimeError(f"DATABASE_URL must be a PostgreSQL URL, got '{url.drivername}'")

    # Supabase hands out postgresql:// URLs; SQLAlchemy async needs the asyncpg driver.
    url = url.set(drivername="postgresql+asyncpg")
    url = url.set(query={k: v for k, v in url.query.items() if k not in ("sslmode", "pgbouncer")})

    connect_args: dict = {
        # Supabase's pooler is PgBouncer, which cannot reuse named prepared statements.
        "statement_cache_size": 0,
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }
    if url.host not in LOCAL_HOSTS:
        connect_args["ssl"] = "require"
    engine_kwargs.setdefault("pool_pre_ping", True)
    return create_async_engine(url, connect_args=connect_args, **engine_kwargs)


def build_test_engine(database_url: str) -> AsyncEngine:
    """No connection reuse, so every test can run on its own event loop."""
    return build_engine(database_url, poolclass=NullPool, pool_pre_ping=False)


engine = build_engine(get_env().database_url, pool_size=5, max_overflow=5)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session
