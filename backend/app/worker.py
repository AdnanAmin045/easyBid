"""arq worker: runs the polling loop as its own process. Start with `arq app.worker.WorkerSettings`."""

from arq import cron
from arq.connections import RedisSettings

from app.config import get_env
from app.main import build_services
from app.services.pipeline import tick


def redis_settings() -> RedisSettings:
    url = get_env().redis_url
    if not url:
        raise RuntimeError("REDIS_URL is not set. Use the Upstash Redis URL that starts with rediss://")
    settings = RedisSettings.from_dsn(url)
    if settings.host.endswith(".upstash.io"):
        # Upstash only accepts TLS, even when the URL was copied as redis://
        settings.ssl = True
    settings.conn_timeout = 10
    settings.conn_retries = 5
    return settings


async def startup(ctx: dict) -> None:
    if not get_env().freelancer_token:
        raise RuntimeError("Missing environment variable: FREELANCER_TOKEN")
    ctx["services"] = build_services()


async def shutdown(ctx: dict) -> None:
    await ctx["services"].freelancer.close()


async def run_tick(ctx: dict) -> None:
    await tick(ctx["services"], owner="worker")


class WorkerSettings:
    redis_settings = redis_settings()
    on_startup = startup
    on_shutdown = shutdown
    # Upstash bills per command and arq sends one every poll, so poll every 5 seconds instead of arq's 0.5.
    poll_delay = 5
    # The tick itself decides what is due, so the poll interval stays configurable in the dashboard.
    # Twice a minute matches the shortest interval the dashboard allows (30 seconds).
    cron_jobs = [cron(run_tick, second={0, 30}, unique=True, timeout=600, keep_result=0)]
