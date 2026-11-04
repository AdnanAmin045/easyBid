"""LinkedIn posting: the text format, the poster, the daily routine and the dashboard API."""

import json
from datetime import timedelta

import httpx
import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import select

from app.config import get_env
from app.db import get_session
from app.linkedin import api as li_api
from app.linkedin import client as li
from app.linkedin import checks, content, engine, research, site
from app.linkedin.client import AppCredentials, LinkedInClient, to_commentary
from app.linkedin.models import LinkedInAccount, LinkedInPost, PostStatus
from app.linkedin.poster import Brand, render_poster
from app.main import app
from app.models import ProfileItem, utcnow
from app.services.llm import LLMError
from app.services.notifier import Notifier
from tests.test_api import login

GOOD_POST = (
    "Most AI agent briefs I read this week had no budget for testing.\n\n"
    "That is the part that decides whether an agent survives its first month.\n\n"
    "Here is what I put in every scope now:\n"
    "1. A list of ten real conversations to replay.\n"
    "2. A person who owns the answers when the agent is wrong.\n"
    "3. A weekly look at the five worst replies.\n\n"
    "None of it is clever. It is the boring part that keeps an agent trusted, and trust is what clients actually pay for.\n\n"
    "What is the first thing you check before you let an automation talk to a customer?"
)

POSTER = {
    "needed": True,
    "template": "points",
    "kicker": "AI agents",
    "headline": "Three checks before an agent talks to customers",
    "points": [{"title": "Replay real chats", "text": "Ten conversations, before launch."}, {"title": "Name an owner", "text": "One person fixes wrong answers."}],
    "stat": "",
    "stat_label": "",
    "caption": "",
}


class FakeWriter:
    """Stands in for the language model: the research search, the planner and the writer."""

    def __init__(self):
        self.calls = 0  # writer calls only
        self.replies: list[dict] = []
        self.prompts: list[str] = []  # writer prompts
        self.plan_prompts: list[str] = []
        self.searches = 0
        self.search_error: LLMError | None = None
        self.idea = {"topic": "Next.js 17 changes caching again", "angle": "What to check before upgrading", "why_now": "Next.js release notes, Vercel blog", "pillar": "Industry shift"}

    async def search(self, *, model, system, user):
        self.searches += 1
        if self.search_error:
            raise self.search_error
        return (
            "Next.js 17 released | Next.js 17 changes the default caching behaviour and adds 40 new codemods. | Vercel blog\n"
            "Postgres 18 adds async IO | Postgres 18 ships asynchronous IO. | PostgreSQL release notes",
            [{"title": "vercel.com", "url": "https://vercel.com/blog/next-17"}],
        )

    async def complete(self, *, model, system, user, schema=None, fallbacks=()):
        if schema and "ideas" in schema["properties"]:
            self.plan_prompts.append(user)
            return json.dumps({"ideas": [self.idea, {**self.idea, "topic": "Second idea"}, {**self.idea, "topic": "Third idea"}]})
        self.calls += 1
        self.prompts.append(user)
        data = self.replies.pop(0) if self.replies else {}
        return json.dumps({"topic": "Upgrading to Next.js 17", "post": GOOD_POST, "hashtags": ["#NextJS", "WebDevelopment", "#bad tag!"], "alt_text": "Three checks", "poster": POSTER, **data})


class FakeLinkedIn:
    """Stands in for linkedin.com behind the real LinkedInClient."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.post_status = 201
        self.userinfo_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/oauth/v2/accessToken":
            return httpx.Response(200, json={"access_token": "li-token", "expires_in": 5184000, "scope": "w_member_social"})
        if path == "/v2/userinfo":
            if self.userinfo_status != 200:
                return httpx.Response(self.userinfo_status, json={"message": "no"})
            return httpx.Response(200, json={"sub": "abc123", "name": "Test Person"})
        if path == "/rest/images":
            return httpx.Response(200, json={"value": {"uploadUrl": "https://upload.linkedin.test/u/1", "image": "urn:li:image:IMG1"}})
        if request.url.host == "upload.linkedin.test":
            return httpx.Response(201)
        if path == "/rest/posts":
            if self.post_status >= 400:
                return httpx.Response(self.post_status, json={"message": "Not enough permissions"})
            return httpx.Response(201, headers={"x-restli-id": "urn:li:share:777"})
        if "/comments" in path:
            return httpx.Response(201, json={})
        return httpx.Response(404)

    def bodies(self, path: str) -> list[dict]:
        return [json.loads(r.content) for r in self.requests if r.url.path == path and r.content]


@pytest.fixture
def linkedin():
    return FakeLinkedIn()


@pytest.fixture
def writer():
    return FakeWriter()


FEEDS = [{"title": "Vercel ships Next.js 17", "url": "https://news.example/next17", "source": "Vercel", "topic": "Next.js"}]
SITE = "[/]\nWe craft software that holds up.\nWeb Platform Engineering\nAI & LLM Integration\nCloud & DevOps\nNext.js, React, FastAPI, PostgreSQL"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """No test reaches the internet: the news feeds and the website are replaced."""

    async def feeds(fields):
        return FEEDS

    async def website(url):
        return SITE

    monkeypatch.setattr(research, "fetch_feeds", feeds)
    monkeypatch.setattr(site, "fetch_site", website)


@pytest_asyncio.fixture
async def li_client(sv, linkedin, writer):
    async def session_override():
        async with sv.sessions() as session:
            yield session

    client = LinkedInClient(
        AppCredentials("pid", "psecret"), AppCredentials("oid", "osecret"), "https://api.test/api/linkedin/callback", "202610",
        transport=httpx.MockTransport(linkedin.handler),
    )
    svc = engine.LinkedInServices(sessions=sv.sessions, llm=writer, client=client, notifier=Notifier("", ""))
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[li_api.services] = lambda: svc
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        http.headers.update(await login(http))
        yield http, svc
    app.dependency_overrides.clear()
    await client.close()


async def connect_personal(http) -> None:
    state = li.make_state(get_env().secret_key, "personal")
    res = await http.get(f"/api/linkedin/callback?state={state}&code=abc", follow_redirects=False)
    assert res.status_code == 303 and "connect=connected" in res.headers["location"], res.headers["location"]


# --- unit ---------------------------------------------------------------------------


def test_text_is_escaped_for_linkedin_but_hashtags_and_known_mentions_become_tags():
    mentions = {"Codevryn": "urn:li:organization:42"}
    text = "We shipped (v2) with C#, 50% faster_ *really*.\nTalk to @Codevryn or @Nobody #AIAgents"
    out = to_commentary(text, mentions)
    assert "\\(v2\\)" in out and "faster\\_" in out and "\\*really\\*" in out
    assert "@[Codevryn](urn:li:organization:42)" in out
    assert "\\@Nobody" in out
    assert out.endswith("#AIAgents")
    assert to_commentary("plain text.", {}) == "plain text."


def test_posts_that_read_like_ai_or_break_the_rules_are_rejected():
    assert checks.post_problem(GOOD_POST, []) is None
    assert "cliche" in checks.post_problem(GOOD_POST.replace("Most", "In today's fast-paced world most"), [])
    assert "too short" in checks.post_problem("Short.", [])
    assert "first line" in checks.post_problem("x" * 200 + "\n\n" + GOOD_POST, [])
    assert "@Bob" in checks.post_problem(GOOD_POST + " Ask @Bob.", ["Codevryn"])
    assert checks.post_problem(GOOD_POST + " @Codevryn", ["Codevryn"]) is None
    assert "emoji" in checks.post_problem(GOOD_POST + " 🚀🔥✅", [])
    assert "—" not in checks.clean_post("One — two **bold** text")


def test_posters_are_drawn_in_the_feed_size_with_and_without_a_logo(tmp_path):
    logo = tmp_path / "logo.png"
    Image.new("RGBA", (400, 120), (255, 0, 0, 255)).save(logo)
    for brand in (Brand(), Brand(logo=logo.read_bytes(), primary="#FFFFFF", accent="#2563EB")):
        for spec in (
            {"template": "points", "headline": "Five things", "points": [{"title": f"Point {i}", "text": "Some detail " * 6} for i in range(5)]},
            {"template": "stat", "stat": "38%", "stat_label": "of briefs name no budget", "caption": "From this week."},
            {"template": "statement", "headline": "A very long sentence " * 8},
        ):
            png = render_poster(spec, brand)
            assert Image.open(__import__("io").BytesIO(png)).size == (1080, 1350)


def test_a_poster_the_writer_cannot_fill_falls_back_to_one_that_works():
    brand = Brand()
    thin = {"needed": True, "template": "points", "headline": "Only a headline", "points": [{"title": "One", "text": ""}]}
    assert checks.poster_from(thin, "auto", "Hook line", brand)["template"] == "statement"
    assert checks.poster_from({"needed": False}, "auto", "Hook", brand) is None
    assert checks.poster_from({"needed": True, **thin}, "never", "Hook", brand) is None
    assert checks.poster_from({"needed": False}, "always", "Hook line here", brand)["headline"] == "Hook line here"
    numbered = {"needed": True, "template": "points", "headline": "H", "points": [{"title": "1. First", "text": ""}, {"title": "2) Second", "text": ""}]}
    assert [p["title"] for p in checks.poster_from(numbered, "auto", "x", brand)["points"]] == ["First", "Second"]


# --- the daily routine and the dashboard --------------------------------------------


async def test_connecting_and_the_forged_state(li_client, sv):
    http, _ = li_client
    overview = (await http.get("/api/linkedin/overview")).json()
    assert [(a["target"], a["connected"]) for a in overview["accounts"]] == [("personal", False), ("company", False)]
    assert "client_id=pid" in (await http.post("/api/linkedin/connect/personal")).json()["url"]

    forged = await http.get("/api/linkedin/callback?state=forged&code=abc", follow_redirects=False)
    assert "connect=error" in forged.headers["location"]
    await connect_personal(http)
    account = (await http.get("/api/linkedin/overview")).json()["accounts"][0]
    assert account["connected"] and account["name"] == "Test Person" and account["days_left"] >= 59
    assert account["author_urn"] == "urn:li:person:abc123"

    # The company page needs its page id before it can be connected.
    assert (await http.post("/api/linkedin/connect/company")).status_code == 409
    # The token is stored encrypted, not as LinkedIn gave it.
    async with sv.sessions() as session:
        saved = await session.scalar(select(LinkedInAccount))
    assert "li-token" not in saved.access_token


async def test_missing_openid_product_is_explained(li_client, linkedin):
    http, _ = li_client
    linkedin.userinfo_status = 403
    state = li.make_state(get_env().secret_key, "personal")
    res = await http.get(f"/api/linkedin/callback?state={state}&code=abc", follow_redirects=False)
    assert "OpenID" in res.headers["location"] or "OpenID" in __import__("urllib.parse").parse.unquote(res.headers["location"])


async def settings_for(http, **personal) -> dict:
    s = (await http.get("/api/linkedin/overview")).json()["settings"]
    s["personal"].update({"enabled": True, "auto_approve": False, "post_time": "23:59", **personal})
    s["generate_time"] = "00:00"
    s["mentions"] = {"Codevryn": "urn:li:organization:42"}
    res = await http.put("/api/linkedin/settings", json=s)
    assert res.status_code == 200, res.text
    return s


async def test_the_daily_post_is_written_once_from_research_and_waits_for_approval(li_client, sv, writer):
    http, svc = li_client
    await connect_personal(http)
    await settings_for(http)
    async with sv.sessions() as session:
        session.add(ProfileItem(kind="project", title="Legal Sparrow", content="Sole developer of a production AI legal SaaS on Next.js and FastAPI"))
        await session.commit()

    await engine.tick(svc)
    await engine.tick(svc)  # the second run finds today's post and writes nothing
    posts = (await http.get("/api/linkedin/posts")).json()
    assert len(posts) == 1 and writer.calls == 1 and writer.searches == 1
    post = posts[0]
    assert post["status"] == "draft" and post["has_poster"] and post["pillar"]
    assert post["text"].endswith("#NextJS #WebDevelopment")  # the broken tag was dropped
    assert post["topic"] == "Upgrading to Next.js 17"
    assert (await http.get(f"/api/linkedin/posts/{post['id']}/poster.png")).headers["content-type"] == "image/png"
    # Why this topic, and where it comes from, is kept with the post.
    assert post["signals"]["why_now"].startswith("Next.js release notes") and post["signals"]["sources"][0]["url"].startswith("https://vercel.com")
    # The planner and the writer saw the research, the profile and the website, and nothing from Freelancer.
    assert "Next.js 17 released" in writer.plan_prompts[0] and "Vercel ships Next.js 17" in writer.prompts[0]
    assert "Legal Sparrow" in writer.prompts[0] and "We craft software that holds up" in writer.prompts[0]
    assert "freelancer_market" not in writer.prompts[0]


async def test_the_search_runs_once_a_day_for_both_profiles_and_the_feeds_take_over_when_it_fails(li_client, writer):
    http, svc = li_client
    s = (await http.get("/api/linkedin/overview")).json()["settings"]
    s["personal"].update({"enabled": True, "post_time": "23:59"})
    s["company"].update({"enabled": True, "post_time": "23:59"})
    s["generate_time"] = "00:00"
    assert (await http.put("/api/linkedin/settings", json=s)).status_code == 200
    await engine.tick(svc)
    assert writer.searches == 1 and len((await http.get("/api/linkedin/posts")).json()) == 2
    # The company's planner is told what the personal profile already chose today.
    assert "Next.js 17 changes caching again" in writer.plan_prompts[1] or "Second idea" in writer.plan_prompts[1] or "Upgrading to Next.js 17" in writer.plan_prompts[1]
    # The profile of the owner is for the personal posts only.
    assert "[project]" not in writer.prompts[1] or "Legal Sparrow" not in writer.prompts[1]

    # A new day's lookup with the search tool out of quota still has the news feeds.
    writer.search_error = LLMError("quota", transient=True)
    refreshed = await http.post("/api/linkedin/research/refresh")
    assert refreshed.status_code == 200 and refreshed.json()["via"] == "feeds" and "Vercel ships Next.js 17" in refreshed.json()["digest"]


async def test_ideas_can_be_asked_for_and_one_written_and_a_repeat_is_avoided(li_client, writer):
    http, svc = li_client
    await connect_personal(http)
    await settings_for(http)
    found = (await http.post("/api/linkedin/ideas", json={"target": "personal", "count": 3})).json()
    assert [i["topic"] for i in found][:2] == ["Next.js 17 changes caching again", "Second idea"] and found[0]["why_now"]
    first = (await http.post("/api/linkedin/posts/generate", json={"target": "personal", "brief": found[0]["topic"]})).json()
    assert found[0]["topic"] in writer.prompts[0]
    # The next idea request is shown the post that was just written, so it can pick something else.
    await http.post("/api/linkedin/ideas", json={"target": "personal"})
    assert first["topic"] in writer.plan_prompts[-1] and "do_not_repeat" in writer.plan_prompts[-1]
    # Every generate is a new post of the day, not a replacement.
    second = (await http.post("/api/linkedin/posts/generate", json={"target": "personal"})).json()
    assert second["id"] != first["id"] and second["slot"] == 1


async def test_the_website_text_can_be_read_again(li_client):
    http, _ = li_client
    assert (await http.get("/api/linkedin/site")).json()["text"] == ""
    refreshed = (await http.post("/api/linkedin/site/refresh")).json()
    assert "AI & LLM Integration" in refreshed["text"]
    assert "Cloud & DevOps" in (await http.get("/api/linkedin/site")).json()["text"]


async def test_approve_edit_and_publish_with_the_poster(li_client, linkedin, sv):
    http, svc = li_client
    await connect_personal(http)
    await settings_for(http, first_comment="Book a call: https://codevryn.com")
    post = (await http.post("/api/linkedin/posts/generate", json={"target": "personal", "brief": "testing agents"})).json()
    assert "testing agents" in svc.llm.prompts[0]

    edited = (await http.patch(f"/api/linkedin/posts/{post['id']}", json={"text": "Edited (with brackets) and @Codevryn #Tag"})).json()
    assert edited["text"].startswith("Edited")
    approved = (await http.post(f"/api/linkedin/posts/{post['id']}/approve", json={})).json()
    assert approved["status"] == "approved"

    # Not due yet: nothing goes out. Due: it does, once.
    async with sv.sessions() as session:
        row = await session.get(LinkedInPost, post["id"])
        row.scheduled_for = utcnow() - timedelta(minutes=1)
        await session.commit()
    await engine.publish_due(svc)
    await engine.publish_due(svc)
    sent = linkedin.bodies("/rest/posts")
    assert len(sent) == 1
    body = sent[0]
    assert body["author"] == "urn:li:person:abc123" and body["visibility"] == "PUBLIC"
    assert "\\(with brackets\\)" in body["commentary"] and "@[Codevryn](urn:li:organization:42)" in body["commentary"]
    assert body["content"]["media"]["id"] == "urn:li:image:IMG1" and body["content"]["media"]["altText"] == "Three checks"
    assert linkedin.bodies("/rest/images")[0]["initializeUploadRequest"]["owner"] == "urn:li:person:abc123"
    headers = next(r.headers for r in linkedin.requests if r.url.path == "/rest/posts")
    assert headers["linkedin-version"] == "202610" and headers["x-restli-protocol-version"] == "2.0.0"
    comment = linkedin.bodies("/rest/socialActions/urn%3Ali%3Ashare%3A777/comments") or [
        json.loads(r.content) for r in linkedin.requests if "/comments" in r.url.path
    ]
    assert comment[0]["message"]["text"] == "Book a call: https://codevryn.com"

    done = (await http.get(f"/api/linkedin/posts/{post['id']}")).json()
    assert done["status"] == "posted" and done["linkedin_url"].endswith("urn:li:share:777/")
    assert (await http.patch(f"/api/linkedin/posts/{post['id']}", json={"text": "late edit"})).status_code == 409


async def test_a_refused_post_is_marked_failed_and_not_retried(li_client, linkedin):
    http, svc = li_client
    await connect_personal(http)
    await settings_for(http)
    post = (await http.post("/api/linkedin/posts/generate", json={"target": "personal"})).json()
    linkedin.post_status = 403
    res = await http.post(f"/api/linkedin/posts/{post['id']}/post-now")
    assert res.status_code == 200
    failed = res.json()
    assert failed["status"] == "failed" and "refused" in failed["error"]
    await engine.publish_due(svc)
    assert len(linkedin.bodies("/rest/posts")) == 1  # not tried again by the scheduler


async def test_an_unconnected_company_page_still_gets_a_draft_to_copy(li_client, sv):
    http, svc = li_client
    s = (await http.get("/api/linkedin/overview")).json()["settings"]
    s["company"].update({"enabled": True, "post_time": "23:59"})
    s["generate_time"] = "00:00"
    assert (await http.put("/api/linkedin/settings", json=s)).status_code == 200
    await engine.tick(svc)
    posts = (await http.get("/api/linkedin/posts?target=company")).json()
    assert len(posts) == 1 and posts[0]["status"] == "draft"
    # It cannot be approved for posting, but can be marked as posted by hand.
    assert (await http.post(f"/api/linkedin/posts/{posts[0]['id']}/approve", json={})).status_code == 409
    assert (await http.post(f"/api/linkedin/posts/{posts[0]['id']}/mark-posted")).json()["status"] == "posted"


async def test_a_bad_draft_is_rewritten_with_the_reason(li_client, writer):
    http, svc = li_client
    await connect_personal(http)
    await settings_for(http)
    writer.replies = [{"post": "Too short."}]
    res = await http.post("/api/linkedin/posts/generate", json={"target": "personal"})
    assert res.status_code == 200 and writer.calls == 2
    assert "too short" in writer.prompts[1]


async def test_settings_are_validated(li_client):
    http, _ = li_client
    s = (await http.get("/api/linkedin/overview")).json()["settings"]
    for change in ({"timezone": "Mars/Base"}, {"generate_time": "25:99"}, {"brand_accent": "blue"}, {"mentions": {"X": "not-a-urn"}}):
        assert (await http.put("/api/linkedin/settings", json={**s, **change})).status_code == 422


FACTS = "Next.js 17 released: 40 new codemods, 87% of sites.\nFull-stack developer. 6 years building web apps. About 1,840 pages read."


def test_made_up_statistics_and_stories_are_caught_but_given_facts_are_allowed():
    assert checks.fact_problem("n8n jobs rose 87% to 58 this week, out of 1,840 projects I saw.", FACTS) is None
    assert checks.fact_problem("I have built web apps for 6 years.", FACTS) is None
    assert checks.fact_problem("Three steps. Start with a list of 10 conversations.", FACTS) is None
    assert "42%" in checks.fact_problem("Agents cut support costs by 42% for most teams.", FACTS)
    assert "$" in checks.fact_problem("A typical build costs $5,000 to start.", FACTS)
    assert "250" in checks.fact_problem("We have 250 happy customers.", FACTS)
    assert "12 clients" in checks.fact_problem("I have worked with 12 clients on this.", FACTS)
    assert "a client told me" in checks.fact_problem("Last spring a client told me their bot was broken.", FACTS)
    assert "we recently" in checks.fact_problem("We recently shipped an agent for a clinic.", FACTS)
    # The same story is fine when the owner's own facts say it happened.
    assert checks.fact_problem("A client told me their bot was broken.", FACTS + "\nA client told me their bot was broken.") is None
    # The poster is held to the same rules.
    bad = {"stat": "73%", "stat_label": "of buyers", "headline": "", "caption": "", "points": []}
    assert "poster" in checks.poster_problem(bad, FACTS)
    assert checks.poster_problem({"stat": "87%", "stat_label": "more n8n jobs", "headline": "", "caption": "", "points": []}, FACTS) is None


def test_the_codevryn_logo_from_the_project_is_used_unchanged(tmp_path):
    shipped = engine.DEFAULT_LOGO.read_bytes()
    assert shipped == (engine.DEFAULT_LOGO.parents[2] / "frontend" / "public" / "logo-png.png").read_bytes()
    s = engine.LinkedInSettings()
    brand = engine.brand_of(s, engine.LinkedInConfig(id=1, data={}))
    assert brand.logo == shipped and brand.accent == "#1E3A5F"
    poster = Image.open(__import__("io").BytesIO(render_poster({"template": "statement", "headline": "Hello there"}, brand))).convert("RGB")
    logo = Image.open(__import__("io").BytesIO(shipped)).convert("RGBA")
    # The logo's own navy appears at the top left, pasted at its original colours.
    navy = (0x1E, 0x3A, 0x5F)
    region = poster.crop((72, 70, 72 + 277, 70 + 64))
    close = sum(1 for p in region.getdata() if all(abs(p[i] - navy[i]) < 12 for i in range(3)))
    assert close > 300
    assert logo.size == (260, 60)
