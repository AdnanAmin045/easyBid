import base64
import email
import json
from email import policy

import httpx
import pytest
import pytest_asyncio

from app.config import get_env
from app.db import get_session
from app.jobs import api as jobs_api
from app.jobs import gmail as gmail_lib
from app.jobs.extract import deobfuscate, find_emails
from app.jobs.gmail import GmailClient
from app.main import app
from app.services.llm import LLMError
from tests.test_api import login

JD = """Senior React Developer (Remote) at Acme Labs
We build logistics dashboards. Requirements: React, TypeScript, Node.js, 4+ years.
To apply, send your CV to careers [at] acmelabs [dot] io with the subject "REACT-42 Application".
Questions? Ask Sara at sara@acmelabs.io. Deadline: 30 October."""

PDF = b"%PDF-1.4 fake cv"


class FakeJobLLM:
    """Answers extraction and writing requests the way the real models do, as JSON."""

    def __init__(self):
        self.fail_extraction = False
        self.bodies: list[str] = []
        self.invented_email = "ceo@unrelated.com"

    def model_problem(self, model):
        return None

    async def complete(self, *, model, system, user, schema=None):
        if "Extract the details" in system:
            if self.fail_extraction:
                raise LLMError("quota exceeded")
            return json.dumps({
                "company": "Acme Labs", "role": "Senior React Developer", "location": "", "work_mode": "remote",
                "recipient_name": "", "emails": ["careers@acmelabs.io", self.invented_email],
                "apply_via": "email", "apply_link": "",
                "apply_instructions": ['Use the subject "REACT-42 Application"'],
                "required_skills": ["React", "TypeScript", "Node.js"], "deadline": "30 October",
            })
        body = self.bodies.pop(0) if self.bodies else "Dear Hiring Team,\n\n" + "I have built React dashboards for logistics teams. " * 8
        return json.dumps({"subject": "REACT-42 Application: Senior React Developer", "body": body})


class FakeGoogle:
    def __init__(self):
        self.sent: list[dict] = []
        self.revoked: list[str] = []
        self.send_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.startswith(gmail_lib.TOKEN_URL):
            form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
            if form["grant_type"] == "authorization_code":
                return httpx.Response(200, json={"access_token": "at-1", "refresh_token": "rt-secret", "expires_in": 3600})
            return httpx.Response(200, json={"access_token": "at-2", "expires_in": 3600})
        if url.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "me@gmail.com"})
        if url.endswith("/messages/send"):
            if self.send_status != 200:
                return httpx.Response(self.send_status, json={"error": {"message": "Rate limit"}})
            self.sent.append(json.loads(request.content))
            return httpx.Response(200, json={"id": f"m{len(self.sent)}", "threadId": f"t{len(self.sent)}"})
        if url.startswith(gmail_lib.REVOKE_URL):
            self.revoked.append(request.content.decode())
            return httpx.Response(200)
        return httpx.Response(404)


@pytest.fixture
def google():
    return FakeGoogle()


@pytest_asyncio.fixture
async def jobs(sv, google):
    async def session_override():
        async with sv.sessions() as session:
            yield session

    async def lookup(domain):
        return domain != "deadmail.dev"

    gmail = GmailClient("cid", "csecret", "https://api.test/api/jobs/gmail/callback", transport=httpx.MockTransport(google.handler))
    js = jobs_api.JobServices(sessions=sv.sessions, llm=FakeJobLLM(), gmail=gmail, lookup=lookup)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[jobs_api.job_services] = lambda: js
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.headers.update(await login(client))
        yield client, js
    app.dependency_overrides.clear()
    await gmail.close()


def test_obfuscated_addresses_are_found_but_prose_is_left_alone():
    text = "Mail hr [at] acme [dot] com or jobs(at)acme.co.uk. We meet at noon at the office. Also X@Y.IO."
    assert find_emails(text) == ["hr@acme.com", "jobs@acme.co.uk", "x@y.io"]
    assert "meet at noon at the office" in deobfuscate(text)
    assert find_emails("Apply through our careers page.") == []


async def connect_gmail(client) -> None:
    state = gmail_lib.make_state(get_env().secret_key)
    res = await client.get(f"/api/jobs/gmail/callback?state={state}&code=abc", follow_redirects=False)
    assert res.status_code == 303 and "gmail=connected" in res.headers["location"]


async def test_gmail_connection(jobs, google):
    client, _ = jobs
    assert (await client.get("/api/jobs/gmail")).json()["connected"] is False
    assert "accounts.google.com" in (await client.post("/api/jobs/gmail/connect")).json()["url"]

    # A forged or expired state is refused.
    res = await client.get("/api/jobs/gmail/callback?state=forged&code=abc", follow_redirects=False)
    assert "gmail=error" in res.headers["location"]

    await connect_gmail(client)
    status = (await client.get("/api/jobs/gmail")).json()
    assert status["connected"] and status["email"] == "me@gmail.com"

    # The refresh token is never stored in the clear.
    async with jobs[1].sessions() as session:
        stored = await jobs_api.store.get_config(session, jobs_api.GMAIL_KEY)
    assert "rt-secret" not in json.dumps(stored)
    assert gmail_lib.decrypt(stored["refresh_token"], get_env().secret_key) == "rt-secret"

    assert (await client.post("/api/jobs/gmail/disconnect")).status_code == 204
    assert google.revoked and (await client.get("/api/jobs/gmail")).json()["connected"] is False


async def test_extract_keeps_only_addresses_in_the_text(jobs):
    client, js = jobs
    res = await client.post("/api/jobs/extract", json={"text": JD})
    data = res.json()
    assert res.status_code == 200
    assert [e["email"] for e in data["emails"]] == ["careers@acmelabs.io", "sara@acmelabs.io"]
    assert all(e["valid"] for e in data["emails"])
    assert data["company"] == "Acme Labs" and data["apply_instructions"]

    # Without the AI, addresses still come from the text scan.
    js.llm.fail_extraction = True
    data = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    assert [e["email"] for e in data["emails"]] == ["careers@acmelabs.io", "sara@acmelabs.io"]
    assert "quota exceeded" in data["warning"]

    bad = (await client.post("/api/jobs/extract", json={"text": "Send your CV to hr@deadmail.dev today please."})).json()
    assert bad["emails"][0]["valid"] is False


async def test_full_application_flow(jobs, google):
    client, js = jobs
    await client.put("/api/jobs/settings", json={"sender_name": "Adnan Amin", "signature": "Adnan Amin\nFull-stack developer"})
    cv = await client.post("/api/jobs/resumes", files={"file": ("adnan-cv.pdf", PDF, "application/pdf")})
    assert cv.status_code == 200 and cv.json()["is_default"]
    await client.post("/api/jobs/profile", json={"kind": "experience", "title": "Built logistics dashboards in React"})

    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    draft = await client.post(
        "/api/jobs/applications",
        json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io", "resume_id": cv.json()["id"]},
    )
    assert draft.status_code == 200, draft.text
    app_id = draft.json()["id"]
    assert draft.json()["status"] == "draft" and draft.json()["body"].endswith("Full-stack developer")

    # Sending needs Gmail.
    assert (await client.post(f"/api/jobs/applications/{app_id}/send", json={})).status_code == 409
    await connect_gmail(client)

    edited = await client.patch(f"/api/jobs/applications/{app_id}", json={"cc": ["sara@acmelabs.io"]})
    assert edited.json()["cc"] == ["sara@acmelabs.io"]

    sent = await client.post(f"/api/jobs/applications/{app_id}/send", json={})
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "sent" and sent.json()["gmail_thread_id"] == "t1"

    message = email.message_from_bytes(base64.urlsafe_b64decode(google.sent[0]["raw"]), policy=policy.default)
    assert message["To"] == "careers@acmelabs.io" and message["Cc"] == "sara@acmelabs.io"
    assert message["From"] == "Adnan Amin <me@gmail.com>"
    assert message["Subject"] == "REACT-42 Application: Senior React Developer"
    (attachment,) = list(message.iter_attachments())
    assert attachment.get_filename() == "adnan-cv.pdf" and attachment.get_content() == PDF

    # A sent application is locked and cannot go out twice.
    assert (await client.post(f"/api/jobs/applications/{app_id}/send", json={})).status_code == 409
    assert (await client.patch(f"/api/jobs/applications/{app_id}", json={"subject": "x"})).status_code == 409

    # A second application to the same company is held back until confirmed.
    second = await client.post(
        "/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "sara@acmelabs.io"}
    )
    second_id = second.json()["id"]
    held = await client.post(f"/api/jobs/applications/{second_id}/send", json={})
    assert held.status_code == 409 and held.json()["detail"].startswith("duplicate")
    assert (await client.post(f"/api/jobs/applications/{second_id}/send", json={"allow_duplicate": True})).status_code == 200

    listed = (await client.get("/api/jobs/applications?q=acme&status=sent")).json()
    assert listed["total"] == 2
    overview = (await client.get("/api/jobs/overview")).json()
    assert overview["sent_today"] == 2 and overview["gmail"]["connected"]


async def test_send_guards(jobs, google):
    client, js = jobs
    await connect_gmail(client)
    await client.put("/api/jobs/settings", json={"daily_send_limit": 1})
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()

    async def draft(to):
        return (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": to})).json()["id"]

    # A Gmail failure is recorded and the draft can be retried.
    first = await draft("careers@acmelabs.io")
    google.send_status = 429
    assert (await client.post(f"/api/jobs/applications/{first}/send", json={})).status_code == 502
    assert (await client.get(f"/api/jobs/applications/{first}")).json()["status"] == "failed"
    google.send_status = 200
    assert (await client.post(f"/api/jobs/applications/{first}/send", json={})).status_code == 200

    # The daily limit holds.
    other = await draft("jobs@other.dev")
    res = await client.post(f"/api/jobs/applications/{other}/send", json={"allow_duplicate": True})
    assert res.status_code == 409 and "Daily send limit" in res.json()["detail"]
    await client.put("/api/jobs/settings", json={"daily_send_limit": 10})

    # Unfilled placeholders never go out.
    await client.patch(f"/api/jobs/applications/{other}", json={"body": "Dear [Hiring Manager], " + "x" * 400})
    res = await client.post(f"/api/jobs/applications/{other}/send", json={})
    assert res.status_code == 422 and "placeholder" in res.json()["detail"]

    # An address whose domain has no mail server is refused.
    await client.patch(f"/api/jobs/applications/{other}", json={"body": "Hello, " + "x" * 400, "to_email": "a@deadmail.dev"})
    res = await client.post(f"/api/jobs/applications/{other}/send", json={})
    assert res.status_code == 422 and "cannot receive email" in res.json()["detail"]
    assert len(google.sent) == 1


async def test_ai_draft_is_rewritten_once_when_it_breaks_the_rules(jobs):
    client, js = jobs
    good = "Dear Hiring Team,\n\n" + "I have shipped React and Node.js products used every day. " * 7
    js.llm.bodies = ["Too short.", good]
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    res = await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})
    assert res.status_code == 200 and res.json()["body"].startswith("Dear Hiring Team")

    js.llm.bodies = ["Too short.", "Still short."]
    res = await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})
    assert res.status_code == 502 and "too short" in res.json()["detail"]


async def test_resumes_and_prompts(jobs):
    client, _ = jobs
    assert (await client.post("/api/jobs/resumes", files={"file": ("cv.exe", b"MZ", "application/octet-stream")})).status_code == 415
    assert (await client.post("/api/jobs/resumes", files={"file": ("cv.pdf", b"not a pdf", "application/pdf")})).status_code == 415
    first = (await client.post("/api/jobs/resumes", files={"file": ("a.pdf", PDF, "application/pdf")})).json()
    second = (await client.post("/api/jobs/resumes", data={"name": "Frontend CV"}, files={"file": ("b.pdf", PDF, "application/pdf")})).json()
    assert first["is_default"] and not second["is_default"] and second["name"] == "Frontend CV"
    await client.post(f"/api/jobs/resumes/{second['id']}/default")
    assert [r["is_default"] for r in (await client.get("/api/jobs/resumes")).json()] == [True, False]
    download = await client.get(f"/api/jobs/resumes/{first['id']}/file")
    assert download.content == PDF and "a.pdf" in download.headers["content-disposition"]

    assert (await client.get("/api/jobs/prompts/current")).json()["builtin"] is True
    for text in ("v1", "v2"):
        await client.post("/api/jobs/prompts", json={"content": text})
    assert (await client.get("/api/jobs/prompts/current")).json() == {"content": "v2", "version": 2, "builtin": False}
    assert [p["is_active"] for p in (await client.get("/api/jobs/prompts")).json()["items"]] == [True, False]
