import os
import tempfile
from pathlib import Path

import pgserver

# A real PostgreSQL server for the test run, so tests exercise the same engine as Supabase.
_postgres = pgserver.get_server(Path(tempfile.gettempdir()) / "easybid_test_pg")

# Must be set before the app is imported.
os.environ.update(
    DATABASE_URL=_postgres.get_uri(),
    FREELANCER_TOKEN="test-token",
    ANTHROPIC_API_KEY="",
    ADMIN_EMAIL="admin@example.com",
    ADMIN_PASSWORD="secret-password",
    SECRET_KEY="test-secret-key-that-is-long-enough-for-hs256",
    EMBEDDED_SCHEDULER="false",
    TELEGRAM_BOT_TOKEN="",
)

import json

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db import build_test_engine
from app.models import Base, utcnow
from app.schemas import AppSettings
from app.services import store
from app.services.freelancer import FreelancerClient
from app.services.llm import Selection
from app.services.notifier import Notifier
from app.services.pipeline import Services


# The schema comes from the real migration, so every test run also checks it.
command.upgrade(Config(str(Path(__file__).parent.parent / "alembic.ini")), "head")


class FakeLLM:
    def problem(self, s):
        return None

    def __init__(self):
        self.apply = True
        self.text = "I have built this exact kind of API before and can start today. " * 3
        self.select_calls = 0
        self.proposal_calls = 0

    async def select(self, prompt, project, profile, s):
        self.select_calls += 1
        return Selection(apply=self.apply, reason="matches my skills" if self.apply else "not a fit")

    async def write_proposal(self, prompt, project, profile, amount, period, s):
        self.proposal_calls += 1
        return self.text


class FakeFreelancer:
    """Stands in for freelancer.com behind the real FreelancerClient."""

    def __init__(self):
        self.projects: list[dict] = []
        self.bids: list[dict] = []
        self.bid_error: tuple[int, dict] | None = None
        self.bid_statuses: dict[int, str] = {}
        self.self_calls = 0
        self.account = {
            "id": 99,
            "username": "me",
            "jobs": [{"id": 759, "name": "React.js"}],
            "status": {"identity_verified": True, "freelancer_verified_user": False},
            "membership_package": {"name": "free"},
            "preferred_freelancer": False,
            "limited_account": False,
            "account_balances": {"bids_remaining": 6, "equivalent_amount": 1.79},
        }

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/users/0.1/self/"):
            self.self_calls += 1
            return self._ok(self.account)
        if path.endswith("/projects/active/"):
            return self._ok({"projects": self.projects})
        if path.endswith("/bids/") and request.method == "POST":
            if self.bid_error:
                status, body = self.bid_error
                return httpx.Response(status, json=body)
            bid =json.loads(request.content)
            bid["id"] = 5000 + len(self.bids)
            self.bids.append(bid)
            return self._ok(bid)
        if path.endswith("/bids/"):
            return self._ok({"bids": [{"id": i, "award_status": s} for i, s in self.bid_statuses.items()]})
        return httpx.Response(404, json={"status": "error", "message": "not found"})

    @staticmethod
    def _ok(result) -> httpx.Response:
        return httpx.Response(200, json={"status": "success", "result": result})


def raw_project(project_id: int = 1, **overrides) -> dict:
    project = {
        "id": project_id,
        "title": "Build a React dashboard",
        "seo_url": "react/build-dashboard",
        "description": "Need a React.js dashboard with charts and a REST API.",
        "type": "fixed",
        "currency": {"code": "USD"},
        "budget": {"minimum": 250, "maximum": 750},
        "bid_stats": {"bid_count": 3, "bid_avg": 400},
        "jobs": [{"id": 759, "name": "React.js"}],
        "language": "en",
        "upgrades": {"NDA": False, "sealed": False},
        "time_submitted": int(utcnow().timestamp()) - 60,
    }
    project.update(overrides)
    return project


@pytest.fixture
def fake_freelancer() -> FakeFreelancer:
    return FakeFreelancer()


@pytest_asyncio.fixture
async def sv(fake_freelancer):
    engine = build_test_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as conn:
        tables = ", ".join(Base.metadata.tables)
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    client = FreelancerClient("test-token", "https://fl.test/api", transport=httpx.MockTransport(fake_freelancer.handler))
    services = Services(sessions=sessions, freelancer=client, llm=FakeLLM(), notifier=Notifier("", ""))
    async with sessions() as session:
        await store.save_settings(session, AppSettings(paused=False, skill_ids=[759], min_skill_matches=1))
        await session.commit()
    yield services
    await client.close()
    await engine.dispose()
