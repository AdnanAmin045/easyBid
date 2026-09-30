import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import public, router
from app.config import get_env
from app.db import SessionLocal
from app.services.freelancer import FreelancerClient
from app.services.llm import LLM
from app.services.notifier import Notifier
from app.services.pipeline import Services, tick

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("easybid")

TICK_SECONDS = 15


def build_services() -> Services:
    env = get_env()
    return Services(
        sessions=SessionLocal,
        freelancer=FreelancerClient(env.freelancer_token, env.freelancer_base_url),
        llm=LLM(env.anthropic_api_key, env.gemini_api_key),
        notifier=Notifier(env.telegram_bot_token, env.telegram_chat_id),
    )


async def scheduler_loop(sv: Services, standby: bool) -> None:
    while True:
        try:
            await tick(sv, owner="web", standby=standby)
        except Exception:
            logger.exception("Scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    env = get_env()
    missing = env.missing_required()
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")

    app.state.services = build_services()
    app.state.skill_cache = []
    # With EMBEDDED_SCHEDULER=false the arq worker polls, and this loop only steps in if the worker goes quiet.
    task = asyncio.create_task(scheduler_loop(app.state.services, standby=not env.embedded_scheduler))
    yield
    task.cancel()
    await app.state.services.freelancer.close()


app = FastAPI(title="EasyBid API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_env().cors_origin_list,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(public)
app.include_router(router)
