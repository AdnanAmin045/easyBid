import httpx
import pytest_asyncio

from app.api import services
from app.db import get_session
from app.main import app
from tests.conftest import raw_project


@pytest_asyncio.fixture
async def client(sv):
    async def session_override():
        async with sv.sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[services] = lambda: sv
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


async def login(client) -> dict:
    res = await client.post("/api/auth/login", json={"email": "Admin@example.com", "password": "secret-password"})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['token']}"}


async def test_auth_is_required(client):
    assert (await client.get("/api/health")).status_code == 200
    assert (await client.get("/api/settings")).status_code == 401
    assert (await client.get("/api/settings", headers={"Authorization": "Bearer nope"})).status_code == 401
    bad = await client.post("/api/auth/login", json={"email": "admin@example.com", "password": "wrong"})
    assert bad.status_code == 401


async def test_full_flow_through_the_api(client, fake_freelancer):
    h = await login(client)

    # Prompts are versioned; saving a new one makes it the active version.
    for content in ("v1 prompt", "v2 prompt"):
        res = await client.post("/api/prompts", json={"kind": "proposal", "content": content}, headers=h)
        assert res.status_code == 200
    prompts = (await client.get("/api/prompts?kind=proposal", headers=h)).json()
    assert [(p["version"], p["is_active"]) for p in prompts] == [(2, True), (1, False)]

    settings = (await client.get("/api/settings", headers=h)).json()
    settings["exclude_keywords"] = ["wordpress"]
    assert (await client.put("/api/settings", json=settings, headers=h)).status_code == 200
    assert (await client.put("/api/settings", json={**settings, "mode": "yolo"}, headers=h)).status_code == 422

    assert (await client.get("/api/account", headers=h)).json()["id"] == 99

    fake_freelancer.projects = [raw_project(1)]
    assert (await client.post("/api/run", headers=h)).json() == {"fetched": 1, "proposed": 1}

    (pending,) = (await client.get("/api/proposals?status=pending", headers=h)).json()
    assert pending["project"]["title"] == "Build a React dashboard"

    # Preview never saves or bids.
    test = await client.post(
        "/api/prompts/test", json={"kind": "proposal", "content": "try this", "project_id": 1}, headers=h
    )
    assert test.status_code == 200 and test.json()["amount"] == 550

    url = f"/api/proposals/{pending['id']}"
    edited = await client.patch(url, json={"text": "Edited " * 30, "amount": 600}, headers=h)
    assert edited.json()["amount"] == 600
    assert fake_freelancer.bids == []

    sent = await client.post(f"{url}/approve", headers=h)
    assert sent.status_code == 200 and sent.json()["status"] == "sent"
    assert fake_freelancer.bids[0]["amount"] == 600
    assert fake_freelancer.bids[0]["description"] == ("Edited " * 30).strip()

    # Sent bids are locked.
    assert (await client.patch(url, json={"amount": 1}, headers=h)).status_code == 409
    assert (await client.post(f"{url}/approve", headers=h)).status_code == 409
    assert (await client.post("/api/projects/1/generate", headers=h)).status_code == 409

    stats = (await client.get("/api/stats", headers=h)).json()
    assert stats["sent_today"] == 1 and stats["prompts"][0]["sent"] == 1

    item = await client.post("/api/profile", json={"kind": "project", "title": "CRM", "content": "Built it"}, headers=h)
    assert (await client.delete(f"/api/profile/{item.json()['id']}", headers=h)).status_code == 204
    assert len((await client.get("/api/logs", headers=h)).json()) >= 2
