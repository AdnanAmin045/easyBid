import asyncio
import logging

import httpx
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import DBAPIError, OperationalError

from app.api import public, router
from app.jobs import api as jobs_api
from app.jobs import accounts as job_accounts
from app.jobs import followups as job_followups
from app.jobs.gmail import GmailClient
from app.linkedin import api as linkedin_api
from app.linkedin import engine as linkedin_engine
from app.linkedin.client import AppCredentials, LinkedInClient
from app.outreach import api as outreach_api
from app.outreach import engine as outreach_engine
from app.config import get_env
from app.db import SessionLocal
from app.services.freelancer import FreelancerClient
from app.services.llm import LLM
from app.services.notifier import Notifier
from app.services.pipeline import Services, tick

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("easybid")

TICK_SECONDS = 15
OUTREACH_TICK_SECONDS = 10
LINKEDIN_TICK_SECONDS = 60
KEEPALIVE_SECONDS = 300


def build_services() -> Services:
    env = get_env()
    return Services(
        sessions=SessionLocal,
        freelancer=FreelancerClient(env.freelancer_token, env.freelancer_base_url),
        llm=LLM(
            env.anthropic_api_key,
            env.gemini_api_keys,
            groq_key=env.groq_api_key,
            cerebras_key=env.cerebras_api_key,
            mistral_key=env.mistral_api_key,
        ),
        notifier=Notifier(env.telegram_bot_token, env.telegram_chat_id),
    )


async def scheduler_loop(sv: Services, standby: bool) -> None:
    while True:
        try:
            await tick(sv, owner="web", standby=standby)
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


async def outreach_loop(js: jobs_api.JobServices) -> None:
    """Sends campaign emails. Safe next to another instance: every claim is a compare-and-set in the database."""
    failures = 0
    while True:
        try:
            await outreach_engine.tick(js)
            await job_followups.tick(js)
            failures = 0
        except (OperationalError, DBAPIError, OSError, TimeoutError) as e:
            # The database is unreachable (network down, Supabase paused). Say so once, briefly, and back off.
            failures += 1
            if failures == 1 or failures % 10 == 0:
                logger.warning("Outreach: database unreachable (%s), retrying with a longer wait", type(e).__name__)
        except Exception:
            failures += 1
            logger.exception("Outreach tick failed")
        # 10 s normally; after repeated failures wait longer, up to 2 minutes.
        await asyncio.sleep(min(OUTREACH_TICK_SECONDS * 2 ** min(failures, 4), 120))


async def linkedin_loop(svc: linkedin_engine.LinkedInServices) -> None:
    """Writes the day's LinkedIn posts and publishes the approved ones that are due."""
    failures = 0
    while True:
        try:
            await linkedin_engine.tick(svc)
            failures = 0
        except (OperationalError, DBAPIError, OSError, TimeoutError) as e:
            failures += 1
            if failures == 1 or failures % 10 == 0:
                logger.warning("LinkedIn: database unreachable (%s), retrying with a longer wait", type(e).__name__)
        except Exception:
            failures += 1
            logger.exception("LinkedIn tick failed")
        await asyncio.sleep(min(LINKEDIN_TICK_SECONDS * 2 ** min(failures, 3), 600))


async def keepalive_loop(url: str) -> None:
    """Render's free plan stops a service after 15 minutes without incoming requests, and polling stops with it.

    A request to the service's own public URL counts as incoming, so this keeps it up while nobody has the
    dashboard open.
    """
    async with httpx.AsyncClient(timeout=30) as http:
        while True:
            await asyncio.sleep(KEEPALIVE_SECONDS)
            try:
                await http.get(f"{url.rstrip('/')}/api/health")
            except httpx.HTTPError as e:
                logger.warning("Keep-alive request failed: %r", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = get_env()
    missing = env.missing_required()
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    app.state.services = build_services()
    app.state.jobs = jobs_api.JobServices(
        sessions=SessionLocal,
        llm=app.state.services.llm,
        gmail=GmailClient(env.google_client_id, env.google_client_secret, env.google_redirect_uri),
        notifier=app.state.services.notifier,
    )
    app.state.linkedin = linkedin_engine.LinkedInServices(
        sessions=SessionLocal,
        llm=app.state.services.llm,
        client=LinkedInClient(
            AppCredentials(env.linkedin_client_id, env.linkedin_client_secret),
            AppCredentials(env.linkedin_org_client_id, env.linkedin_org_client_secret),
            env.linkedin_callback,
            env.linkedin_api_version,
        ),
        notifier=app.state.services.notifier,
    )
    async with SessionLocal() as session:
        await job_accounts.sync_env_smtp(session, env)
        await session.commit()
    app.state.skill_cache = []
    # With EMBEDDED_SCHEDULER=false the arq worker polls, and this loop only steps in if the worker goes quiet.
    tasks = [asyncio.create_task(scheduler_loop(app.state.services, standby=not env.embedded_scheduler))]
    tasks.append(asyncio.create_task(outreach_loop(app.state.jobs)))
    tasks.append(asyncio.create_task(linkedin_loop(app.state.linkedin)))
    if env.render_external_url:
        tasks.append(asyncio.create_task(keepalive_loop(env.render_external_url)))
    yield
    for task in tasks:
        task.cancel()
    await app.state.services.freelancer.close()
    await app.state.jobs.gmail.close()
    await app.state.linkedin.client.close()


app = FastAPI(title="EasyBid API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_env().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(public)
app.include_router(router)
app.include_router(jobs_api.public)
app.include_router(jobs_api.router)
app.include_router(outreach_api.router)
app.include_router(linkedin_api.public)
app.include_router(linkedin_api.alias)
app.include_router(linkedin_api.router)
