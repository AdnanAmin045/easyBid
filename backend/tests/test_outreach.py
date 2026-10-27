import asyncio
import base64
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.db import get_session
from app.jobs import api as jobs_api
from app.jobs.gmail import GmailClient
from app.jobs.models import ApplicationStatus, GmailAccount, JobApplication
from app.main import app
from app.models import utcnow
from app.outreach import engine, importer, render
from app.outreach.models import Campaign, Recipient
from app.services.llm import LLMError
from tests.test_api import login
from tests.test_jobs import FakeGoogle, connect_gmail

NOW = utcnow()


def at(seconds: float):
    return NOW + timedelta(seconds=seconds)


# --- fakes ------------------------------------------------------------------------


class OutreachGoogle(FakeGoogle):
    """FakeGoogle plus threads, and failures that can be switched on per test."""

    def __init__(self):
        super().__init__()
        self.threads: dict[str, list[dict]] = {}
        self.send_error: tuple[int, str] | None = None
        self.drop_connection = False
        self.thread_reads = 0

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/threads/" in url:
            self.thread_reads += 1
            thread_id = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(200, json={"messages": self.threads.get(thread_id, [])})
        if url.endswith("/messages/send"):
            if self.drop_connection:
                raise httpx.ReadTimeout("timed out")
            if self.send_error:
                status, message = self.send_error
                return httpx.Response(status, json={"error": {"message": message}})
        return super().handler(request)


class OutreachLLM:
    def __init__(self):
        self.calls: list[dict] = []
        self.template_answers: list[dict] = []
        self.fail = False

    def model_problem(self, model):
        return None

    async def complete(self, *, model, system, user, schema=None):
        self.calls.append({"system": system, "user": user})
        if self.fail:
            raise LLMError("quota exceeded")
        if "email templates" in system:
            answer = self.template_answers.pop(0) if self.template_answers else {
                "subject": "Quick question, {{first_name|there}}",
                "body": "{Hi|Hello} {{first_name|there}},\n\nI help teams like {{company|yours}} ship faster. " * 2,
            }
            return json.dumps(answer)
        name = next((line.split(": ", 1)[1] for line in user.splitlines() if line.startswith("name: ")), "friend")
        return json.dumps({"subject": f"Idea for {name}", "body": f"Hello {name},\n\nI would love to work with you on something useful for your team."})


@pytest.fixture
def google():
    return OutreachGoogle()


@pytest.fixture
def llm():
    return OutreachLLM()


@pytest_asyncio.fixture
async def outreach(sv, google, llm):
    async def session_override():
        async with sv.sessions() as session:
            yield session

    async def lookup(domain):
        return domain != "deadmail.dev"

    gmail = GmailClient("cid", "csecret", "https://api.test/api/jobs/gmail/callback", transport=httpx.MockTransport(google.handler))
    js = jobs_api.JobServices(sessions=sv.sessions, llm=llm, gmail=gmail, lookup=lookup)
    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[jobs_api.job_services] = lambda: js
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        client.headers.update(await login(client))
        await client.put("/api/jobs/settings", json={"sender_name": "Adnan Amin", "signature": "Adnan Amin\nFull-stack developer"})
        yield client, js
    app.dependency_overrides.clear()
    await gmail.close()


def sent_mail(google: OutreachGoogle) -> list:
    """Every email Gmail was asked to send, parsed."""
    return [message_from_bytes(base64.urlsafe_b64decode(m["raw"]), policy=policy.default) for m in google.sent]


async def make_campaign(client, **overrides) -> dict:
    body = {
        "name": "Agencies",
        "subject_template": "Quick question, {{first_name|there}}",
        "body_template": "{Hi|Hello} {{first_name|there}},\n\nI saw {{company|your team}} is growing and wanted to say hello.",
        # Open all day, every day, with a fixed pace and no warm-up, so tests control time themselves.
        "window_start_hour": 0,
        "window_end_hour": 24,
        "weekdays_only": False,
        "ramp_up": False,
        "min_delay_seconds": 60,
        "max_delay_seconds": 60,
        "daily_limit": 100,
    }
    res = await client.post("/api/outreach/campaigns", json={**body, **overrides})
    assert res.status_code == 200, res.text
    return res.json()


async def import_text(client, campaign_id: int, text: str, **options) -> dict:
    res = await client.post(f"/api/outreach/campaigns/{campaign_id}/recipients/import", json={"text": text, **options})
    assert res.status_code == 200, res.text
    return res.json()


async def start(client, campaign_id: int) -> dict:
    res = await client.post(f"/api/outreach/campaigns/{campaign_id}/start")
    assert res.status_code == 200, res.text
    return res.json()


async def recipients(client, campaign_id: int, **params) -> list[dict]:
    res = await client.get(f"/api/outreach/campaigns/{campaign_id}/recipients", params={"page_size": 100, **params})
    return res.json()["items"]


async def run_until_done(js, google, limit=50, step=61) -> int:
    """Tick with the clock moving forward until nothing more is sent."""
    sent = 0
    for i in range(limit):
        sent += await engine.tick(js, now=at(i * step))
    return sent


LIST = """email,name,company
ann.lee@acmelabs.io,Ann Lee,Acme Labs
bob@globex.io,Bob Stone,Globex
carol@initech.io,,Initech
"""


# --- rendering and parsing --------------------------------------------------------


def test_template_variables_fallbacks_and_options():
    ctx = render.context("ann@acme.io", "Ann Lee", "", {"Job Title": "CTO"})
    out = render.render("Hi {{first_name}} ({{ Job_Title }}) at {{company|your company}}, {{missing}}", ctx)
    assert out.text == "Hi Ann (CTO) at your company, "
    assert out.missing == ["missing"]

    # An option is picked once per seed, so previews match what is sent, and both words do occur.
    picks = {render.render("{Hi|Hello|Hey} there", {}, seed=i).text for i in range(40)}
    assert picks == {"Hi there", "Hello there", "Hey there"}
    assert render.render("{Hi|Hello}", {}, seed=7).text == render.render("{Hi|Hello}", {}, seed=7).text

    # Values from the sheet are inserted as they are, never read as templates themselves.
    tricky = render.render("Hi {{name}}", {"name": "{a|b}"})
    assert tricky.text == "Hi {a|b}"

    assert render.unknown_variables("{{first_name}} {{nope}} {{maybe|x}} {{industry}}", {"industry"}) == ["nope"]
    assert render.variables_in("{{A b}} {{a_b}} {{c}}") == ["a_b", "c"]


def test_sheet_with_header_keeps_own_subject_and_multiline_body():
    text = (
        "Email;First Name;Last Name;Company;Subject;Message;Industry\n"
        'ann@acme.io;Ann;Lee;Acme;"Hello Ann";"Line one\nLine two";Logistics\n'
        "ann@ACME.io;Ann;Lee;Acme;;;\n"
        "not-an-email;X;;;;;\n"
        ";;;;;;\n"
    )
    sheet = importer.parse(text)
    assert sheet.has_header and sheet.columns == ["industry"]
    (row,) = sheet.rows
    assert (row.email, row.name, row.company, row.subject) == ("ann@acme.io", "Ann Lee", "Acme", "Hello Ann")
    assert row.body == "Line one\nLine two" and row.fields == {"industry": "Logistics"}
    assert [r.reason for r in sheet.rejected] == ["Duplicate in this list", "Not a valid email address"]


def test_pasted_free_text_finds_every_address():
    sheet = importer.parse(
        "ann@acme.io, bob@globex.io; carol [at] initech [dot] io\n"
        "Dana Fox <dana@umbrella.io>\n"
        "just some words\n"
        "ann@acme.io\n"
    )
    assert [(r.email, r.name) for r in sheet.rows] == [
        ("ann@acme.io", ""),
        ("bob@globex.io", ""),
        ("carol@initech.io", ""),
        ("dana@umbrella.io", "Dana Fox"),
    ]
    assert {r.reason for r in sheet.rejected} == {"No email address found", "Duplicate in this list"}


# --- campaigns end to end ---------------------------------------------------------


async def test_template_campaign_sends_each_personalised_email_with_a_pause_between(outreach, google):
    client, js = outreach
    campaign = await make_campaign(client)
    result = await import_text(client, campaign["id"], LIST + "ann.lee@acmelabs.io,Dup,\nx@deadmail.dev,Dead,Dead Inc\nnope,,\n")
    assert (result["added"], result["held_back"], result["rejected_total"]) == (4, 1, 2)
    assert result["rejected"][0]["reason"] in ("Not a valid email address", "Duplicate in this list")

    # Nothing can start before Gmail is connected.
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    assert res.status_code == 409 and "Connect Gmail" in res.text
    await connect_gmail(client)

    check = (await client.get(f"/api/outreach/campaigns/{campaign['id']}/check")).json()
    assert check["ready"] and check["pending"] == 3 and check["with_missing"] == 0

    preview = (await client.get(f"/api/outreach/campaigns/{campaign['id']}/preview")).json()
    assert preview["email"] == "ann.lee@acmelabs.io" and "Ann" in preview["body"] and "Acme Labs" in preview["body"]
    assert preview["body"].endswith("Adnan Amin\nFull-stack developer")

    assert (await start(client, campaign["id"]))["status"] == "running"

    # The first email goes at once; the next ones wait for the random pause (fixed at 60 s here).
    assert await engine.tick(js, now=at(0)) == 1
    assert await engine.tick(js, now=at(30)) == 0
    assert len(google.sent) == 1
    assert await engine.tick(js, now=at(61)) == 1
    assert await engine.tick(js, now=at(122)) == 1
    assert await engine.tick(js, now=at(183)) == 0

    mails = sent_mail(google)
    assert [m["To"] for m in mails] == ["ann.lee@acmelabs.io", "bob@globex.io", "carol@initech.io"]
    assert mails[0]["Subject"] == "Quick question, Ann"
    assert "Acme Labs" in mails[0].get_content() and mails[0].get_content().rstrip().endswith("Full-stack developer")
    assert mails[2]["Subject"] == "Quick question, there"  # no name: the fallback is used
    assert "your team" not in mails[1].get_content() and "Globex" in mails[1].get_content()

    done = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert done["status"] == "completed" and done["counts"] == {"sent": 3, "skipped": 1}
    held = await recipients(client, campaign["id"], status="skipped")
    assert "cannot receive email" in held[0]["error"]


async def test_prebuilt_emails_from_a_sheet_are_sent_as_written(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    campaign = await make_campaign(client, subject_template="", body_template="", append_signature=False, name="Prebuilt")
    sheet = io.StringIO()
    w = csv.writer(sheet)
    w.writerow(["email", "subject", "body", "company"])
    w.writerow(["ann@acmelabs.io", "Partnership with Acme", "Dear Ann,\n\nHere is my own text for you.\n\nBest,\nMe", "Acme"])
    w.writerow(["bob@globex.io", "For {{company}}", "Hi Bob,\n\nWritten for {{company}} only.", "Globex"])
    result = await import_text(client, campaign["id"], sheet.getvalue())
    assert result["with_own_content"] == 2

    await start(client, campaign["id"])  # no campaign template needed when every row brings its own
    assert await run_until_done(js, google, limit=4) == 2
    first, second = sent_mail(google)
    assert first["Subject"] == "Partnership with Acme"
    assert first.get_content().rstrip() == "Dear Ann,\n\nHere is my own text for you.\n\nBest,\nMe"  # no signature added
    assert second["Subject"] == "For Globex" and "Written for Globex only." in second.get_content()


async def test_rows_without_any_content_block_the_start(outreach):
    client, _ = outreach
    await connect_gmail(client)
    campaign = await make_campaign(client, subject_template="", body_template="")
    await import_text(client, campaign["id"], "ann@acmelabs.io")
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    assert res.status_code == 409 and "no template" in res.text


async def test_missing_variable_fails_that_recipient_and_sends_nothing_broken(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    campaign = await make_campaign(
        client, subject_template="About {{industry}}", body_template="Hi {{first_name|there}}, a note on {{industry}} for you and your team today."
    )
    await import_text(client, campaign["id"], "email,name,industry\nann@acmelabs.io,Ann,Logistics\nbob@globex.io,Bob,\n")

    check = (await client.get(f"/api/outreach/campaigns/{campaign['id']}/check")).json()
    assert check["with_missing"] == 1 and check["missing_examples"][0]["missing"] == ["industry"]
    assert check["ready"]

    await start(client, campaign["id"])
    assert await run_until_done(js, google, limit=4) == 1
    (mail,) = sent_mail(google)
    assert mail["To"] == "ann@acmelabs.io" and mail["Subject"] == "About Logistics"
    (failed,) = await recipients(client, campaign["id"], status="failed")
    assert failed["email"] == "bob@globex.io" and "industry" in failed["error"]

    # Fixing the value and retrying sends it.
    await client.patch(f"/api/outreach/campaigns/{campaign['id']}/recipients/{failed['id']}", json={"fields": {"industry": "Retail"}})
    assert (await client.post(f"/api/outreach/campaigns/{campaign['id']}/recipients/{failed['id']}/retry")).json()["status"] == "pending"
    # A finished campaign that gets someone to write to again waits for the user to resume it.
    reopened = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert reopened["status"] == "paused" and "Resume" in reopened["pause_reason"]
    assert await engine.tick(js, now=at(1000)) == 0
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(1000)) == 1
    assert sent_mail(google)[1]["Subject"] == "About Retail"


async def test_window_daily_limit_and_warm_up_hold_sending_back(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    addresses = "\n".join(f"person{i}@acmelabs.io" for i in range(8))

    # Closed right now: a window of one hour that is not the current hour in UTC.
    other_hour = (NOW.hour + 6) % 24
    closed = await make_campaign(client, name="Closed", window_start_hour=other_hour, window_end_hour=other_hour + 1)
    await import_text(client, closed["id"], addresses)
    state = await start(client, closed["id"])
    assert "Outside the sending window" in state["waiting"]
    assert await engine.tick(js, now=NOW) == 0 and not google.sent
    await client.post(f"/api/outreach/campaigns/{closed['id']}/pause")

    # Daily limit: 2 per rolling 24 hours, then it waits and carries on the next day.
    capped = await make_campaign(client, name="Capped", daily_limit=2)
    await import_text(client, capped["id"], addresses.replace("person", "capped"))
    await start(client, capped["id"])
    assert sum([await engine.tick(js, now=at(i * 61)) for i in range(6)]) == 2
    waiting = (await client.get(f"/api/outreach/campaigns/{capped['id']}")).json()["waiting"]
    assert waiting is None or "Daily limit" in waiting
    assert await engine.tick(js, now=at(86400 + 600)) == 1

    # Warm-up: 10 on day one even though the limit is 100.
    warm = engine.daily_allowance(Campaign(ramp_up=True, daily_limit=100, started_at=NOW), at(3600))
    assert warm == 10 and engine.daily_allowance(Campaign(ramp_up=True, daily_limit=100, started_at=NOW), at(3 * 86400 + 5)) == 40


async def test_account_limit_counts_job_applications_too(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    await client.put("/api/outreach/settings", json={"daily_limit": 3, "min_gap_seconds": 5, "skip_recent_days": 30, "bounce_pause_percent": 8, "model": "gemini-3.5-flash"})
    async with js.sessions() as session:
        mailbox = (await session.scalars(select(GmailAccount))).one()
        for i in range(2):
            session.add(
                JobApplication(
                    status=ApplicationStatus.SENT, source_text="x", to_email=f"job{i}@co.io", sent_at=NOW - timedelta(hours=1),
                    last_contact_at=NOW - timedelta(hours=1), gmail_account_id=mailbox.id,
                )
            )
        await session.commit()
    campaign = await make_campaign(client)
    await import_text(client, campaign["id"], "a@acmelabs.io\nb@acmelabs.io\nc@acmelabs.io")
    await start(client, campaign["id"])
    assert await run_until_done(js, google, limit=6) == 1  # 3 allowed in total, 2 already used by applications
    assert "Account limit" in (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()["waiting"]


# --- failures ---------------------------------------------------------------------


async def running_with(client, text="a@acmelabs.io\nb@globex.io", **overrides) -> dict:
    await connect_gmail(client)
    campaign = await make_campaign(client, **overrides)
    await import_text(client, campaign["id"], text)
    await start(client, campaign["id"])
    return campaign


async def test_rate_limit_pauses_the_campaign_and_keeps_the_recipient_pending(outreach, google):
    client, js = outreach
    campaign = await running_with(client)
    google.send_error = (429, "Rate limit exceeded")
    assert await engine.tick(js, now=at(0)) == 0
    state = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert state["status"] == "paused" and "limiting" in state["pause_reason"]
    assert state["counts"] == {"pending": 2}

    # After the user resumes, the same recipient goes first.
    google.send_error = None
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(10)) == 1
    assert sent_mail(google)[0]["To"] == "a@acmelabs.io"


async def test_server_errors_are_retried_with_a_growing_wait_and_then_fail(outreach, google):
    client, js = outreach
    campaign = await running_with(client, text="a@acmelabs.io")
    google.send_error = (503, "Backend error")
    assert await engine.tick(js, now=at(0)) == 0
    (r,) = await recipients(client, campaign["id"])
    assert r["status"] == "pending" and r["attempts"] == 1 and "Backend error" in r["error"]
    assert await engine.tick(js, now=at(60)) == 0  # waiting 5 minutes
    assert google.sent == []
    await engine.tick(js, now=at(400))
    await engine.tick(js, now=at(400 + 700))
    (r,) = await recipients(client, campaign["id"])
    assert r["status"] == "failed" and r["attempts"] == 3
    # A permanent refusal is not retried at all.
    campaign2 = await make_campaign(client, name="Bad address")
    await import_text(client, campaign2["id"], "z@acmelabs.io")
    await start(client, campaign2["id"])
    google.send_error = (400, "Invalid To header")
    await engine.tick(js, now=at(5000))
    assert (await recipients(client, campaign2["id"]))[0]["status"] == "failed"


async def test_unknown_outcome_is_never_retried(outreach, google):
    client, js = outreach
    campaign = await running_with(client, text="a@acmelabs.io")
    google.drop_connection = True
    assert await engine.tick(js, now=at(0)) == 0
    (r,) = await recipients(client, campaign["id"])
    assert r["status"] == "failed" and "Sent folder" in r["error"] and r["attempts"] == 1
    google.drop_connection = False
    assert await engine.tick(js, now=at(1000)) == 0 and google.sent == []


async def test_revoked_access_pauses_every_running_campaign(outreach, google):
    client, js = outreach
    first = await running_with(client, text="a@acmelabs.io")
    second = await make_campaign(client, name="Second")
    await import_text(client, second["id"], "b@globex.io")
    await start(client, second["id"])
    google.send_error = (401, "Invalid Credentials")
    await engine.tick(js, now=at(0))
    for c in (first, second):
        state = (await client.get(f"/api/outreach/campaigns/{c['id']}")).json()
        assert state["status"] == "paused" and "revoked" in state["pause_reason"]
    assert (await client.get(f"/api/outreach/campaigns/{first['id']}")).json()["counts"] == {"pending": 1}


async def test_two_senders_at_the_same_moment_send_one_email(outreach, google):
    client, js = outreach
    await running_with(client, text="a@acmelabs.io\nb@acmelabs.io\nc@acmelabs.io")
    sent = await asyncio.gather(*(engine.tick(js, now=at(0)) for _ in range(5)))
    assert sum(sent) == 1 and len(google.sent) == 1


async def test_a_send_interrupted_by_a_crash_is_flagged_not_repeated(outreach, google):
    client, js = outreach
    campaign = await running_with(client, text="a@acmelabs.io")
    async with js.sessions() as session:
        await session.execute(update(Recipient).values(status="sending", updated_at=NOW - timedelta(minutes=30)))
        await session.commit()
    await engine.tick(js, now=NOW)
    (r,) = await recipients(client, campaign["id"])
    assert r["status"] == "failed" and "Sent folder" in r["error"] and google.sent == []


# --- do-not-contact, history, replies ---------------------------------------------


async def test_do_not_contact_list_and_recent_history_protect_people(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    campaign = await make_campaign(client)
    await import_text(client, campaign["id"], "a@acmelabs.io\nb@globex.io\nc@initech.io")

    res = await client.post("/api/outreach/suppressions", json={"emails": "B@globex.io\nnobody", "reason": "asked to stop"})
    assert res.json() == {"added": 1, "already_listed": 0, "ignored": 1}
    assert (await client.post("/api/outreach/suppressions", json={"emails": "b@globex.io"})).json()["already_listed"] == 1
    (held,) = await recipients(client, campaign["id"], status="skipped")
    assert held["email"] == "b@globex.io" and "do-not-contact" in held["error"]
    # A suppressed address cannot be forced back in.
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/recipients/{held['id']}/retry")
    assert res.status_code == 409

    await start(client, campaign["id"])
    assert await run_until_done(js, google, limit=4) == 2

    # A new campaign: addresses written to a moment ago, and a job application, are held back.
    async with js.sessions() as session:
        session.add(JobApplication(status=ApplicationStatus.SENT, source_text="x", to_email="d@hooli.io", sent_at=utcnow() - timedelta(days=2)))
        await session.commit()
    second = await make_campaign(client, name="Second")
    result = await import_text(client, second["id"], "a@acmelabs.io\nd@hooli.io\ne@pied.io")
    assert result["held_back"] == 2
    reasons = {r["email"]: r["error"] for r in await recipients(client, second["id"], status="skipped")}
    assert "Already written to" in reasons["a@acmelabs.io"] and "applied" in reasons["d@hooli.io"]

    # The user can override a hold deliberately.
    forced = next(r for r in await recipients(client, second["id"], status="skipped") if r["email"] == "a@acmelabs.io")
    res = await client.post(f"/api/outreach/campaigns/{second['id']}/recipients/{forced['id']}/retry", params={"allow_recent": "true"})
    assert res.json()["status"] == "pending"
    # Not holding anything back when the user asks for the whole list.
    third = await make_campaign(client, name="Third")
    assert (await import_text(client, third["id"], "a@acmelabs.io", skip_recent=False))["held_back"] == 0


async def test_replies_are_noticed_and_bounces_suppress_and_pause(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    await client.put("/api/outreach/settings", json={"daily_limit": 100, "min_gap_seconds": 5, "skip_recent_days": 30, "bounce_pause_percent": 20, "model": "gemini-3.5-flash"})
    campaign = await make_campaign(client)
    await import_text(client, campaign["id"], "\n".join(f"p{i}@acmelabs.io" for i in range(12)))
    await start(client, campaign["id"])
    assert await run_until_done(js, google, limit=14) == 12

    def header(sender, auto=None):
        headers = [{"name": "From", "value": sender}] + ([{"name": "Auto-Submitted", "value": auto}] if auto else [])
        return {"id": "reply", "payload": {"headers": headers}}

    mine = lambda n: {"id": f"m{n}", "payload": {"headers": [{"name": "From", "value": "Adnan <me@gmail.com>"}]}}
    google.threads["t1"] = [mine(1), header("Ann <p0@acmelabs.io>")]
    google.threads["t2"] = [mine(2), header("p1@acmelabs.io", auto="auto-replied")]  # out of office: not a reply
    for n in range(3, 8):
        google.threads[f"t{n}"] = [mine(n), header("Mail Delivery Subsystem <mailer-daemon@googlemail.com>")]
    # Several passes, as the loop would do over time.
    for i in range(6):
        await engine.check_replies(js, at(i * 1000 + 100000))
    states = {r["email"]: r["status"] for r in await recipients(client, campaign["id"])}
    assert states["p0@acmelabs.io"] == "replied"
    assert states["p1@acmelabs.io"] == "sent"
    assert [e for e, s in states.items() if s == "bounced"] == [f"p{i}@acmelabs.io" for i in range(2, 7)]

    suppressed = (await client.get("/api/outreach/suppressions", params={"q": "acmelabs"})).json()
    assert suppressed["total"] == 5 and all(i["reason"] == "Bounced" for i in suppressed["items"])
    state = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert state["status"] in ("completed", "paused")  # 5 of 12 bounced is above the 20% line, but it had finished already
    reads = google.thread_reads
    await engine.check_replies(js, at(100000 + 6 * 1000 + 5))  # nothing is due again so soon
    assert google.thread_reads <= reads + 5


async def test_a_high_bounce_rate_pauses_a_running_campaign(outreach, google):
    client, js = outreach
    campaign = await running_with(client, text="\n".join(f"p{i}@acmelabs.io" for i in range(14)))
    for i in range(10):
        await engine.tick(js, now=at(i * 61))
    for n in range(1, 4):
        google.threads[f"t{n}"] = [
            {"id": f"m{n}", "payload": {"headers": [{"name": "From", "value": "me@gmail.com"}]}},
            {"id": "b", "payload": {"headers": [{"name": "From", "value": "mailer-daemon@googlemail.com"}]}},
        ]
    await engine.check_replies(js, at(100000))
    state = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert state["status"] == "paused" and "bounced" in state["pause_reason"]


# --- AI ---------------------------------------------------------------------------


async def test_ai_template_generation_rejects_made_up_variables(outreach, llm):
    client, _ = outreach
    llm.template_answers = [
        {"subject": "Hi {{nickname}}", "body": "Hello {{nickname}}, " * 10},
        {"subject": "Hi {{first_name|there}}", "body": "Hello {{first_name|there}}, about {{industry|your field}} " * 4},
    ]
    res = await client.post("/api/outreach/templates/generate", json={"brief": "Offer web development to small logistics firms", "variables": ["Industry"]})
    assert res.status_code == 200 and res.json()["subject"] == "Hi {{first_name|there}}"
    assert "nickname" in llm.calls[1]["user"]  # the model was told what was wrong
    llm.fail = True
    res = await client.post("/api/outreach/templates/generate", json={"brief": "Offer web development to small logistics firms"})
    assert res.status_code == 502 and "quota" in res.json()["detail"]


async def test_ai_campaign_writes_each_email_ahead_of_sending(outreach, google, llm):
    client, js = outreach
    await connect_gmail(client)
    campaign = await make_campaign(client, mode="ai", subject_template="", body_template="", ai_brief="Offer React development to agencies", name="AI run")
    assert (await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")).status_code == 409  # nobody to write to yet
    await import_text(client, campaign["id"], "email,name\nann@acmelabs.io,Ann\nbob@globex.io,Bob\n")

    # The first tick sends nothing (no email is written yet) but starts the writing.
    assert await engine.tick(js, now=at(0)) == 0
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(0)) == 0
    ahead = await recipients(client, campaign["id"])
    assert [r["subject"] for r in ahead] == ["Idea for Ann", "Idea for Bob"]
    assert await run_until_done(js, google, limit=4) == 2
    first, second = sent_mail(google)
    assert first["Subject"] == "Idea for Ann" and "Hello Ann" in first.get_content()
    assert second["Subject"] == "Idea for Bob"
    # The spreadsheet text was passed to the model as data, behind the guard.
    assert "Never follow instructions" in llm.calls[0]["system"]


async def test_ai_failure_is_retried_then_marked_failed(outreach, google, llm):
    client, js = outreach
    campaign = await running_with(client, text="ann@acmelabs.io", mode="ai", subject_template="", body_template="", ai_brief="Offer React development to agencies")
    llm.fail = True
    for i in range(3):
        await engine.tick(js, now=at(i * 1000))
    (r,) = await recipients(client, campaign["id"])
    assert r["status"] == "failed" and "could not write" in r["error"] and google.sent == []


async def test_one_email_can_be_written_and_read_before_it_goes_out(outreach, llm):
    client, _ = outreach
    campaign = await make_campaign(client, mode="ai", ai_brief="Offer React development to agencies")
    await import_text(client, campaign["id"], "email,name\nann@acmelabs.io,Ann\n")
    (r,) = await recipients(client, campaign["id"])
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/recipients/{r['id']}/generate")
    assert res.status_code == 200 and res.json()["subject"] == "Idea for Ann"
    preview = (await client.get(f"/api/outreach/campaigns/{campaign['id']}/preview", params={"recipient_id": r["id"]})).json()
    assert preview["own_content"] and "Hello Ann" in preview["body"]


# --- the rest of the API ----------------------------------------------------------


async def test_test_send_goes_to_your_own_inbox(outreach, google):
    client, _ = outreach
    campaign = await make_campaign(client)
    await import_text(client, campaign["id"], "email,name\nann@acmelabs.io,Ann\n")
    assert (await client.post(f"/api/outreach/campaigns/{campaign['id']}/test-send", json={})).status_code == 409
    await connect_gmail(client)
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/test-send", json={})
    assert res.json() == {"sent_to": "me@gmail.com"}
    (mail,) = sent_mail(google)
    assert mail["To"] == "me@gmail.com" and mail["Subject"] == "[TEST] Quick question, Ann"
    # A test is not a send: the recipient is still waiting.
    assert (await recipients(client, campaign["id"]))[0]["status"] == "pending"


async def test_campaign_rules_and_lifecycle(outreach, google):
    client, js = outreach
    bad = await client.post("/api/outreach/campaigns", json={"name": "x", "min_delay_seconds": 100, "max_delay_seconds": 50})
    assert bad.status_code == 422
    assert (await client.post("/api/outreach/campaigns", json={"name": "x", "window_start_hour": 10, "window_end_hour": 10})).status_code == 422
    assert (await client.post("/api/outreach/campaigns", json={"name": "x", "timezone": "Mars/Base"})).status_code == 422
    assert (await client.post("/api/outreach/campaigns", json={"name": "x", "min_delay_seconds": 2})).status_code == 422

    campaign = await make_campaign(client)
    cid = campaign["id"]
    patched = await client.patch(f"/api/outreach/campaigns/{cid}", json={"name": "Renamed", "max_delay_seconds": 90})
    assert patched.json()["name"] == "Renamed" and patched.json()["max_delay_seconds"] == 90
    assert (await client.patch(f"/api/outreach/campaigns/{cid}", json={"min_delay_seconds": 500})).status_code == 422  # above the max
    assert (await client.patch(f"/api/outreach/campaigns/{cid}", json={"bogus": 1})).status_code == 422

    await connect_gmail(client)
    await import_text(client, cid, "a@acmelabs.io\nb@acmelabs.io\nc@acmelabs.io")
    # Re-importing the same list adds nothing.
    again = await import_text(client, cid, "a@acmelabs.io\nnew@acmelabs.io")
    assert (again["added"], again["rejected_total"]) == (1, 1)

    await start(client, cid)
    assert (await client.delete(f"/api/outreach/campaigns/{cid}")).status_code == 409  # running
    await engine.tick(js, now=at(0))
    assert (await client.post(f"/api/outreach/campaigns/{cid}/pause")).json()["status"] == "paused"
    assert await engine.tick(js, now=at(1000)) == 0  # paused means paused
    assert (await client.delete(f"/api/outreach/campaigns/{cid}")).status_code == 409  # it has sent emails
    cancelled = (await client.post(f"/api/outreach/campaigns/{cid}/cancel")).json()
    assert cancelled["status"] == "cancelled" and cancelled["counts"] == {"sent": 1, "skipped": 3}
    assert (await client.post(f"/api/outreach/campaigns/{cid}/start")).status_code == 409
    assert (await client.post(f"/api/outreach/campaigns/{cid}/recipients/import", json={"text": "q@acmelabs.io"})).status_code == 409

    empty = await make_campaign(client, name="Never used")
    assert (await client.delete(f"/api/outreach/campaigns/{empty['id']}")).status_code == 204
    listing = (await client.get("/api/outreach/campaigns", params={"q": "renamed"})).json()
    assert [c["name"] for c in listing["items"]] == ["Renamed"] and listing["items"][0]["counts"]["sent"] == 1


async def test_templates_library_and_overview(outreach):
    client, _ = outreach
    body = {"name": "Intro", "subject": "Hello {{first_name|there}}", "body": "Short text for {{company|you}}."}
    created = (await client.post("/api/outreach/templates", json=body)).json()
    assert (await client.post("/api/outreach/templates", json=body)).status_code == 409
    updated = (await client.put(f"/api/outreach/templates/{created['id']}", json={**body, "name": "Intro v2"})).json()
    assert updated["name"] == "Intro v2" and len(( await client.get("/api/outreach/templates")).json()) == 1
    assert (await client.delete(f"/api/outreach/templates/{created['id']}")).status_code == 204

    overview = (await client.get("/api/outreach/overview")).json()
    assert overview["gmail"]["connected"] is False and overview["daily_limit"] == 60 and overview["sent_24h"] == 0
    assert (await client.put("/api/outreach/settings", json={"daily_limit": 9999})).status_code == 422


async def test_export_neutralises_spreadsheet_formulas(outreach):
    client, _ = outreach
    campaign = await make_campaign(client)
    await import_text(client, campaign["id"], "email,name\nann@acmelabs.io,=HYPERLINK(\"http://evil\")\n")
    res = await client.get(f"/api/outreach/campaigns/{campaign['id']}/export")
    assert res.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(res.text)))
    assert rows[0][:4] == ["email", "name", "company", "status"]
    assert rows[1][0] == "ann@acmelabs.io" and rows[1][1].startswith("'=")


async def test_import_limits(outreach):
    client, _ = outreach
    campaign = await make_campaign(client)
    big = "\n".join(f"u{i}@acmelabs.io" for i in range(5001))
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/recipients/import", json={"text": big})
    assert res.status_code == 413
    nothing = await import_text(client, campaign["id"], "no addresses here at all")
    assert nothing["added"] == 0 and nothing["rejected_total"] == 1
    assert (await client.get("/api/outreach/campaigns/999")).status_code == 404
    unauth = await httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test").get("/api/outreach/overview")
    assert unauth.status_code == 401


# --- two-column sheets and Excel files --------------------------------------------

FULL_EMAIL = "Subject: Hello from Adnan\n\nDear Ann,\n\nHere is my complete email.\n\nBest,\nAdnan"


def workbook(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    book = Workbook()
    for row in rows:
        book.active.append(row)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def test_two_columns_without_a_header_are_address_and_whole_email():
    text = f'ann@acmelabs.io\t"{FULL_EMAIL}"\nbob@globex.io\t"No subject line here, only text."\n'
    sheet = importer.parse(text)
    ann, bob = sheet.rows
    assert not sheet.has_header
    assert (ann.subject, ann.body.startswith("Dear Ann,"), ann.body.endswith("Adnan")) == ("Hello from Adnan", True, True)
    assert (bob.subject, bob.body) == ("", "No subject line here, only text.")
    # A plain list of addresses is still a list of addresses.
    assert [r.email for r in importer.parse("a@x.io, b@y.io\nc@z.io").rows] == ["a@x.io", "b@y.io", "c@z.io"]


def test_excel_with_and_without_a_header():
    with_header = importer.parse_xlsx(workbook([["Receiver", "Full Email"], ["ann@acmelabs.io", FULL_EMAIL], [None, None], ["bad", "x"]]))
    (row,) = with_header.rows
    assert with_header.has_header and row.subject == "Hello from Adnan" and "complete email" in row.body
    assert with_header.rejected[0].reason == "Not a valid email address" and with_header.rejected[0].line == 4

    plain = importer.parse_xlsx(workbook([["ann@acmelabs.io", "First text"], ["bob@globex.io", "Second text"]]))
    assert [(r.email, r.body) for r in plain.rows] == [("ann@acmelabs.io", "First text"), ("bob@globex.io", "Second text")]
    with pytest.raises(ValueError):
        importer.parse_xlsx(b"this is not a zip")


async def test_excel_upload_sends_each_whole_email_as_written(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    campaign = await make_campaign(client, subject_template="", body_template="", append_signature=False)
    data = workbook([["ann@acmelabs.io", FULL_EMAIL], ["bob@globex.io", "Subject: For Bob\n\nHi Bob, my own words."]])
    res = await client.post(
        f"/api/outreach/campaigns/{campaign['id']}/recipients/import-file",
        files={"file": ("list.xlsx", data, "application/octet-stream")},
        data={"check_domains": "false"},
    )
    assert res.status_code == 200, res.text
    assert (res.json()["added"], res.json()["with_own_content"]) == (2, 2)

    await start(client, campaign["id"])
    assert await run_until_done(js, google, limit=4) == 2
    first, second = sent_mail(google)
    assert first["To"] == "ann@acmelabs.io" and first["Subject"] == "Hello from Adnan"
    assert first.get_content().strip() == "Dear Ann,\n\nHere is my complete email.\n\nBest,\nAdnan"
    assert second["Subject"] == "For Bob" and second.get_content().strip() == "Hi Bob, my own words."

    # Bad files are refused clearly.
    other = await make_campaign(client, name="Other")
    bad = await client.post(f"/api/outreach/campaigns/{other['id']}/recipients/import-file", files={"file": ("x.xlsx", b"nope", "application/octet-stream")})
    assert bad.status_code == 415 and "Excel" in bad.json()["detail"]
    csv_file = await client.post(
        f"/api/outreach/campaigns/{other['id']}/recipients/import-file",
        files={"file": ("x.csv", b"email,name\nzed@acmelabs.io,Zed\n", "text/csv")},
        data={"check_domains": "false"},
    )
    assert csv_file.json()["added"] == 1


def test_columns_in_any_order_are_told_apart_by_content():
    long = "Dear Ann,\n\nThis is my complete message for you with enough words in it.\n\nBest,\nAdnan"
    # subject, message, address (no header, tab separated like a paste from Excel)
    text = f'Hello Ann\t"{long}"\tann@acmelabs.io\nHello Bob\t"{long.replace("Ann", "Bob")}"\tbob@globex.io\n'
    ann, bob = importer.parse(text).rows
    assert (ann.email, ann.subject, ann.body) == ("ann@acmelabs.io", "Hello Ann", long)
    assert bob.subject == "Hello Bob" and "Dear Bob" in bob.body

    # message, address in an Excel file without a header
    plain = importer.parse_xlsx(workbook([[long, "ann@acmelabs.io"], ["Short note", "bob@globex.io"]]))
    assert [(r.email, r.body) for r in plain.rows] == [("ann@acmelabs.io", long), ("bob@globex.io", "Short note")]

    # With a header the names decide, whatever the order.
    shuffled = importer.parse("body,email,subject\n\"Text for Ann\",ann@acmelabs.io,Hi\n")
    assert (shuffled.rows[0].email, shuffled.rows[0].subject, shuffled.rows[0].body) == ("ann@acmelabs.io", "Hi", "Text for Ann")

    # Addresses spread over several columns are still just a list.
    assert [r.email for r in importer.parse("a@x.io\tb@y.io\nc@z.io\td@w.io").rows] == ["a@x.io", "b@y.io", "c@z.io", "d@w.io"]


async def test_new_campaign_defaults_are_kept_in_settings_and_validated(outreach):
    client, _ = outreach
    saved = (await client.get("/api/outreach/settings")).json()
    assert saved["default_window_start_hour"] == 0 and saved["default_window_end_hour"] == 24  # around the clock until changed

    changed = {**saved, "default_timezone": "Asia/Karachi", "default_window_start_hour": 8, "default_window_end_hour": 20, "default_weekdays_only": False}
    res = await client.put("/api/outreach/settings", json=changed)
    assert res.status_code == 200 and (await client.get("/api/outreach/settings")).json()["default_timezone"] == "Asia/Karachi"

    assert (await client.put("/api/outreach/settings", json={**changed, "default_timezone": "Mars/Base"})).status_code == 422
    assert (await client.put("/api/outreach/settings", json={**changed, "default_window_end_hour": 8})).status_code == 422
    assert (await client.put("/api/outreach/settings", json={**changed, "default_max_delay_seconds": 20, "default_min_delay_seconds": 60})).status_code == 422


async def test_the_waiting_message_says_which_window_and_time_zone_it_waits_for(outreach):
    client, js = outreach
    campaign = await make_campaign(client, window_start_hour=9, window_end_hour=18, timezone="UTC", weekdays_only=True)
    async with js.sessions() as session:
        text = engine.window_reason(await session.get(Campaign, campaign["id"]), datetime(2026, 11, 1, 22, 0, tzinfo=timezone.utc))
    assert "09:00 to 18:00 UTC" in text and "weekdays only" in text and "Sun 22:00" in text and "Next send Mon 09:00" in text


def test_a_column_that_says_it_holds_the_email_text_is_the_message():
    for header in ("Email Content", "email_content", "Personalised Email", "Message", "Email Body", "Mail Text"):
        text = f'email,name,{header},subject\nann@acmelabs.io,Ann,"Hi Ann,\n\nThe whole message.",Hello\n'
        row = importer.parse(text).rows[0]
        assert row.body == "Hi Ann,\n\nThe whole message." and row.subject == "Hello", header
        assert importer.parse(text).columns == []  # it is the message, not a template variable

    # Other columns stay variables, and an explicit body column wins over a guess.
    text = "email,notes,body,email_content\nann@acmelabs.io,likes dogs,Real body,Other\n"
    sheet = importer.parse(text)
    assert sheet.rows[0].body == "Real body" and sheet.columns == ["notes", "email_content"]
    assert importer.parse("email,last_message_date\nann@acmelabs.io,2026-01-01\n").rows[0].body == ""


async def test_import_warns_when_a_long_text_column_was_not_taken_as_the_message(outreach):
    client, _ = outreach
    campaign = await make_campaign(client)
    long_text = "word " * 60
    res = await import_text(client, campaign["id"], f"email,notes\nann@acmelabs.io,{long_text}\n")
    assert res["warnings"] and "'notes'" in res["warnings"][0]
    ok = await make_campaign(client, name="Fine")
    assert (await import_text(client, ok["id"], f"email,email_content\nann@acmelabs.io,{long_text}\n"))["warnings"] == []
