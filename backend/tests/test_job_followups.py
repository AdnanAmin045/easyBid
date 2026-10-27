import base64
import json
from datetime import timedelta
from email import message_from_bytes, policy

import httpx

from app.jobs import followups
from app.models import utcnow
from tests.test_jobs import JD, connect_gmail, google, jobs  # noqa: F401  (fixtures)

PLAN = [
    {"days": 5, "subject": "", "body": "Hello, I am following up on my application for the {{role|open}} role at {{company|your company}}."},
    {"days": 7, "subject": "Still interested in {{company}}", "body": "A last short note on my application. Thank you for your time."},
]
DAY = timedelta(days=1)


def mails(google):
    return [message_from_bytes(base64.urlsafe_b64decode(m["raw"]), policy=policy.default) for m in google.sent]


def with_threads(client, google, threads: dict):
    """Let the fake Google also answer thread reads."""
    original = google.handler

    def handler(request):
        if "/threads/" in str(request.url):
            return httpx.Response(200, json={"messages": threads.get(request.url.path.rsplit("/", 1)[-1], [])})
        return original(request)

    return handler


async def sent_application(client, google, js, plan=PLAN):
    await connect_gmail(client)
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    app = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})).json()
    assert (await client.put(f"/api/jobs/applications/{app['id']}/followups", json={"followups": plan})).status_code == 200
    sent = await client.post(f"/api/jobs/applications/{app['id']}/send", json={})
    assert sent.status_code == 200, sent.text
    return sent.json()


async def test_application_follow_ups_go_in_the_same_thread_after_the_chosen_days(jobs, google):
    client, js = jobs
    await connect_gmail(client)
    await client.put("/api/jobs/settings", json={"signature": "Adnan Amin", "default_followups": PLAN[:1]})
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    draft = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})).json()
    assert [f["days"] for f in draft["followups"]] == [5]  # a new application starts with the defaults

    # The plan can be changed before sending, then the application goes out.
    await client.put(f"/api/jobs/applications/{draft['id']}/followups", json={"followups": PLAN})
    app = (await client.post(f"/api/jobs/applications/{draft['id']}/send", json={})).json()
    assert app["status"] == "sent" and len(app["followups"]) == 2 and app["followups_sent"] == 0
    first = mails(google)[0]

    start = utcnow()
    assert await followups.tick(js, now=start + 4 * DAY) == 0  # not due yet
    assert await followups.tick(js, now=start + 5 * DAY + timedelta(minutes=1)) == 1
    one = mails(google)[1]
    assert one["To"] == "careers@acmelabs.io" and one["Subject"] == "Re: " + first["Subject"]
    assert "following up on my application for the Senior React Developer role at Acme Labs" in one.get_content()
    assert one.get_content().rstrip().endswith("Adnan Amin")
    assert one["In-Reply-To"] == first["Message-ID"]
    assert google.sent[1]["threadId"] == app["gmail_thread_id"] and "threadId" not in google.sent[0]

    # The next one counts from the follow-up, with its own subject. Then nothing more is sent.
    assert await followups.tick(js, now=start + 11 * DAY) == 0
    assert await followups.tick(js, now=start + 12 * DAY + timedelta(minutes=2)) == 1
    assert mails(google)[2]["Subject"] == "Still interested in Acme Labs"
    assert await followups.tick(js, now=start + 40 * DAY) == 0 and len(google.sent) == 3
    done = (await client.get(f"/api/jobs/applications/{app['id']}")).json()
    assert done["followups_sent"] == 2 and done["outcome"] == ""


async def test_a_reply_stops_the_follow_ups_and_is_shown(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js)
    thread = app["gmail_thread_id"]
    answer = [
        {"id": app["id"], "payload": {"headers": [{"name": "From", "value": "me@gmail.com"}]}},
        {"id": "x", "payload": {"headers": [{"name": "From", "value": "Sara <sara@acmelabs.io>"}]}},
    ]
    js.gmail._http._transport = httpx.MockTransport(with_threads(client, google, {thread: answer}))

    start = utcnow()
    assert await followups.tick(js, now=start + 6 * DAY) == 0  # due, but she answered
    state = (await client.get(f"/api/jobs/applications/{app['id']}")).json()
    assert state["outcome"] == "replied" and len(google.sent) == 1
    assert await followups.tick(js, now=start + 30 * DAY) == 0 and len(google.sent) == 1


async def test_replies_and_bounces_are_noticed_even_without_follow_ups(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js, plan=[])
    bounce = [
        {"id": "m1", "payload": {"headers": [{"name": "From", "value": "me@gmail.com"}]}},
        {"id": "b", "payload": {"headers": [{"name": "From", "value": "Mail Delivery Subsystem <mailer-daemon@googlemail.com>"}]}},
    ]
    js.gmail._http._transport = httpx.MockTransport(with_threads(client, google, {app["gmail_thread_id"]: bounce}))
    await followups.tick(js, now=utcnow() + timedelta(minutes=30))
    assert (await client.get(f"/api/jobs/applications/{app['id']}")).json()["outcome"] == "bounced"
    # A bounced address goes on the do-not-contact list that outreach campaigns use too.
    listed = (await client.get("/api/outreach/suppressions")).json()["items"]
    assert [s["email"] for s in listed] == ["careers@acmelabs.io"]


async def test_follow_ups_can_be_cancelled_and_are_validated(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js)
    url = f"/api/jobs/applications/{app['id']}/followups"
    assert (await client.put(url, json={"followups": [{"days": 1, "body": "b"}] * 6})).status_code == 422
    assert (await client.put(url, json={"followups": [{"days": 0, "body": "b"}]})).status_code == 422
    res = await client.put(url, json={"followups": [{"days": 40, "body": "b"}, {"days": 30, "body": "b"}]})
    assert res.status_code == 422 and "60 days" in res.text
    assert (await client.put("/api/jobs/applications/999/followups", json={"followups": []})).status_code == 404

    # Cancelled after sending: nothing goes out.
    assert (await client.put(url, json={"followups": []})).json()["followups"] == []
    assert await followups.tick(js, now=utcnow() + 30 * DAY) == 0 and len(google.sent) == 1


async def test_job_follow_up_failures_do_not_duplicate_or_send_blind(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js, plan=PLAN[:1])
    due = utcnow() + 6 * DAY
    original = google.handler

    # If the conversation cannot be read, nothing is sent.
    js.gmail._http._transport = httpx.MockTransport(lambda r: httpx.Response(500, json={"error": {"message": "down"}}) if "/threads/" in str(r.url) else original(r))
    assert await followups.tick(js, now=due) == 0 and len(google.sent) == 1
    note = (await client.get(f"/api/jobs/applications/{app['id']}")).json()
    assert "Could not check" in note["followup_note"] and note["followups_sent"] == 0

    # A follow-up interrupted by a crash is skipped, never repeated.
    async with js.sessions() as session:
        from sqlalchemy import update

        from app.jobs.models import JobApplication

        await session.execute(update(JobApplication).values(followup_claim_at=due - timedelta(minutes=30), followup_retry_at=None))
        await session.commit()
    js.gmail._http._transport = httpx.MockTransport(original)
    assert await followups.tick(js, now=due + timedelta(hours=1)) == 0
    state = (await client.get(f"/api/jobs/applications/{app['id']}")).json()
    assert state["followups_sent"] == 1 and "interrupted" in state["followup_note"] and len(google.sent) == 1


async def test_a_follow_up_added_after_sending_counts_from_the_send_date_and_still_skips_replies(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js, plan=[])
    assert (await client.put(f"/api/jobs/applications/{app['id']}/followups", json={"followups": PLAN[:1]})).status_code == 200
    start = utcnow()
    assert await followups.tick(js, now=start + 2 * DAY) == 0  # 5 days after the real send, not after adding it
    assert await followups.tick(js, now=start + 10 * DAY) == 1  # long overdue: goes at once
    assert len(google.sent) == 2

    # Someone who answered is left alone, however late the follow-up was added.
    other = await client.post("/api/jobs/applications", json={"source_text": JD, "details": (await client.post("/api/jobs/extract", json={"text": JD})).json(), "to_email": "sara@acmelabs.io"})
    sent = await client.post(f"/api/jobs/applications/{other.json()['id']}/send", json={"allow_duplicate": True})
    assert sent.status_code == 200
    await client.put(f"/api/jobs/applications/{other.json()['id']}/followups", json={"followups": PLAN[:1]})
    google.inbox.append({"id": "n1", "from": "Sara <sara@acmelabs.io>"})
    assert await followups.tick(js, now=start + 30 * DAY) == 0 and len(google.sent) == 3
    assert (await client.get(f"/api/jobs/applications/{other.json()['id']}")).json()["outcome"] == "replied"
