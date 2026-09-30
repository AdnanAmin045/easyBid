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
    prompts = (await client.get("/api/prompts?kind=proposal", headers=h)).json()["items"]
    assert (await client.get("/api/prompts/current?kind=proposal", headers=h)).json()["version"] == 2
    assert (await client.get("/api/prompts/current?kind=selection", headers=h)).json() is None
    assert [(p["version"], p["is_active"]) for p in prompts] == [(2, True), (1, False)]

    settings = (await client.get("/api/settings", headers=h)).json()
    settings["exclude_keywords"] = ["wordpress"]
    assert (await client.put("/api/settings", json=settings, headers=h)).status_code == 200
    assert (await client.put("/api/settings", json={**settings, "mode": "yolo"}, headers=h)).status_code == 422

    assert (await client.get("/api/account", headers=h)).json()["id"] == 99

    fake_freelancer.projects = [raw_project(1)]
    assert (await client.post("/api/run", headers=h)).json() == {"fetched": 1, "proposed": 1}

    (pending,) = (await client.get("/api/proposals?status=pending", headers=h)).json()["items"]
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
    assert (await client.get("/api/logs", headers=h)).json()["total"] >= 2


async def test_search_and_pagination(client, sv, fake_freelancer):
    h = await login(client)
    await client.post("/api/prompts", json={"kind": "proposal", "content": "Write it"}, headers=h)
    fake_freelancer.projects = [raw_project(i, title=f"React dashboard {i}") for i in range(1, 24)]
    fake_freelancer.projects += [
        raw_project(30, title="Node.js API for a 100% remote team", description="Express and MongoDB"),
        raw_project(31, title="Landing page", description="Uses snake_case naming", type="hourly"),
    ]
    async with sv.sessions() as session:
        from app.services import store

        settings = await store.get_settings(session)
        await store.save_settings(session, settings.model_copy(update={"max_projects_per_cycle": 50}))
        await session.commit()
    await client.post("/api/run", headers=h)

    async def get(path):
        res = await client.get(f"/api{path}", headers=h)
        assert res.status_code == 200, res.text
        return res.json()

    # Pages do not overlap and the totals describe the whole result.
    first = await get("/projects?page=1&page_size=10")
    third = await get("/projects?page=3&page_size=10")
    assert (first["total"], first["pages"], first["page"], first["page_size"]) == (25, 3, 1, 10)
    assert len(first["items"]) == 10 and len(third["items"]) == 5
    assert not {p["id"] for p in first["items"]} & {p["id"] for p in third["items"]}
    assert (await get("/projects?page=9&page_size=10"))["items"] == []

    # Search is case-insensitive and covers title, description and skill tags.
    assert (await get("/projects?q=REACT%20dashboard"))["total"] == 23
    assert [p["id"] for p in (await get("/projects?q=mongodb"))["items"]] == [30]
    assert (await get("/projects?q=react.js"))["total"] == 25  # the skill tag
    # % and _ are searched literally, not as wildcards.
    assert [p["id"] for p in (await get("/projects?q=100%25"))["items"]] == [30]
    assert [p["id"] for p in (await get("/projects?q=snake_case"))["items"]] == [31]
    assert (await get("/projects?q=snakeXcase"))["total"] == 0

    # Filters combine with search.
    assert (await get("/projects?type=hourly"))["total"] == 1
    assert (await get("/projects?status=proposed&q=dashboard&page_size=5"))["pages"] == 5

    # Proposals search the project title and the proposal text.
    assert (await get("/proposals?status=pending&q=node.js"))["total"] == 1
    assert (await get("/proposals?q=built%20this%20exact"))["total"] == 25
    assert (await get("/proposals?status=sent"))["total"] == 0

    assert (await get("/logs?q=proposed"))["total"] >= 1
    assert (await get("/logs?level=error"))["total"] == 0
    assert (await get("/profile?q=anything"))["items"] == []

    for bad in ("/projects?page=0", "/projects?page_size=101", "/logs?level=loud"):
        assert (await client.get(f"/api{bad}", headers=h)).status_code == 422
