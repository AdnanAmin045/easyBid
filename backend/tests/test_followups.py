from datetime import timedelta

import httpx
from sqlalchemy import update

from app.outreach import engine
from app.outreach.models import Campaign, Recipient
from tests.test_jobs import connect_gmail
from tests.test_outreach import (  # noqa: F401  (fixtures)
    NOW,
    at,
    google,
    import_text,
    llm,
    make_campaign,
    outreach,
    recipients,
    sent_mail,
    start,
)

DAY = 86400
PLAN = [
    {"days": 3, "subject": "", "body": "Hi {{first_name|there}}, just following up on my note about {{company|your team}}."},
    {"days": 4, "subject": "Last try, {{first_name|there}}", "body": "One more nudge from me, and then I will leave you in peace."},
]
LIST = "ann.lee@acmelabs.io,Ann Lee,Acme Labs\nbob@globex.io,Bob Stone,Globex\ncarol@initech.io,,\n"


def thread_with(google, thread_id, sender, auto=None):
    headers = [{"name": "From", "value": sender}] + ([{"name": "Auto-Submitted", "value": auto}] if auto else [])
    google.threads[thread_id] = [
        {"id": "first", "payload": {"headers": [{"name": "From", "value": "me@gmail.com"}]}},
        {"id": "answer", "payload": {"headers": headers}},
    ]


async def first_round(client, js, followups=PLAN, text=LIST):
    """A campaign whose first emails have all gone out."""
    await connect_gmail(client)
    campaign = await make_campaign(client, followups=followups)
    await import_text(client, campaign["id"], "email,name,company\n" + text)
    await start(client, campaign["id"])
    for i in range(text.count("\n")):
        assert await engine.tick(js, now=at(i * 61)) == 1
    return campaign


async def test_follow_ups_go_in_the_same_thread_after_the_chosen_days_and_skip_people_who_replied(outreach, google):
    client, js = outreach
    campaign = await first_round(client, js)
    cid = campaign["id"]
    first = sent_mail(google)
    assert len(first) == 3

    # Nothing is due yet, and the campaign is not finished: three people are waiting for a follow-up.
    assert await engine.tick(js, now=at(2 * DAY)) == 0
    state = (await client.get(f"/api/outreach/campaigns/{cid}")).json()
    assert state["status"] == "running" and state["followups_scheduled"] == 3 and state["followups_sent"] == 0

    thread_with(google, "t2", "Bob <bob@globex.io>")  # Bob answered
    sent = [await engine.tick(js, now=at(3 * DAY + 100 + i * 61)) for i in range(4)]
    assert sum(sent) == 2  # Bob's is not sent
    mails = sent_mail(google)[3:]
    assert [m["To"] for m in mails] == ["ann.lee@acmelabs.io", "carol@initech.io"]
    ann = mails[0]
    assert ann["Subject"] == "Re: Quick question, Ann"
    assert "following up on my note about Acme Labs" in ann.get_content() and ann.get_content().rstrip().endswith("Full-stack developer")
    assert ann["In-Reply-To"] == first[0]["Message-ID"] and ann["References"] == first[0]["Message-ID"]
    assert google.sent[3]["threadId"] == "t1" and google.sent[4]["threadId"] == "t3"
    assert mails[1].get_content().startswith("Hi there,")  # no name: the fallback

    states = {r["email"]: (r["status"], r["followups_sent"]) for r in await recipients(client, cid)}
    assert states == {"ann.lee@acmelabs.io": ("sent", 1), "bob@globex.io": ("replied", 0), "carol@initech.io": ("sent", 1)}

    # The second follow-up counts from the first one and has its own subject. Bob stays out for good.
    assert sum([await engine.tick(js, now=at(7 * DAY + 500 + i * 61)) for i in range(3)]) == 2
    last = sent_mail(google)[5:]
    assert last[0]["Subject"] == "Last try, Ann" and last[1]["Subject"] == "Last try, there"
    done = (await client.get(f"/api/outreach/campaigns/{cid}")).json()
    assert done["status"] == "completed" and done["followups_sent"] == 4 and done["followups_scheduled"] == 0
    assert await engine.tick(js, now=at(30 * DAY)) == 0 and len(google.sent) == 7


async def test_an_out_of_office_answer_does_not_stop_the_follow_up(outreach, google):
    client, js = outreach
    await first_round(client, js, followups=PLAN[:1], text="ann.lee@acmelabs.io,Ann Lee,Acme Labs\n")
    thread_with(google, "t1", "ann.lee@acmelabs.io", auto="auto-replied")
    assert await engine.tick(js, now=at(3 * DAY + 100)) == 1


async def test_follow_ups_obey_the_daily_limit_and_stop_for_bounces_and_suppression(outreach, google):
    client, js = outreach
    campaign = await first_round(client, js, followups=PLAN[:1])
    cid = campaign["id"]
    await client.patch(f"/api/outreach/campaigns/{cid}", json={"daily_limit": 1})
    # A bounce arrives for Bob; Carol asks not to be contacted.
    thread_with(google, "t2", "Mail Delivery Subsystem <mailer-daemon@googlemail.com>")
    await client.post("/api/outreach/suppressions", json={"emails": "carol@initech.io"})
    base = 3 * DAY + 100
    assert sum([await engine.tick(js, now=at(base + i * 61)) for i in range(4)]) == 1
    assert [m["To"] for m in sent_mail(google)[3:]] == ["ann.lee@acmelabs.io"]
    states = {r["email"]: r["status"] for r in await recipients(client, cid)}
    assert states["bob@globex.io"] == "bounced"
    assert "Bounced" in {s["reason"] for s in (await client.get("/api/outreach/suppressions")).json()["items"]}
    assert len(google.sent) == 4


async def test_follow_up_failures_never_double_send_or_send_blind(outreach, google):
    client, js = outreach
    campaign = await first_round(client, js, followups=PLAN[:1], text="ann.lee@acmelabs.io,Ann Lee,Acme Labs\n")
    cid = campaign["id"]
    due = 3 * DAY + 100

    # If the conversation cannot be read, nothing is sent.
    working = google.handler

    def broken(request):
        if "/threads/" in str(request.url):
            return httpx.Response(500, json={"error": {"message": "backend error"}})
        return working(request)

    js.gmail._http._transport = httpx.MockTransport(broken)
    assert await engine.tick(js, now=at(due)) == 0
    assert len(google.sent) == 1
    (r,) = await recipients(client, cid)
    assert r["status"] == "sent" and "Could not check" in r["error"] and r["followups_sent"] == 0
    js.gmail._http._transport = httpx.MockTransport(working)

    # A server error is retried later; an unknown outcome is never repeated.
    google.send_error = (503, "Backend error")
    assert await engine.tick(js, now=at(due + 1000)) == 0
    assert (await recipients(client, cid))[0]["followups_sent"] == 0
    google.send_error = None
    google.drop_connection = True
    assert await engine.tick(js, now=at(due + 5000)) == 0
    (r,) = await recipients(client, cid)
    assert r["followups_sent"] == 1 and "Sent folder" in r["error"] and len(google.sent) == 1
    google.drop_connection = False
    assert await engine.tick(js, now=at(due + 9000)) == 0 and len(google.sent) == 1


async def test_follow_up_with_a_missing_value_is_skipped_and_an_interrupted_one_is_not_repeated(outreach, google):
    client, js = outreach
    plan = [{"days": 1, "subject": "", "body": "About {{industry}} again, a short follow-up note for you."}]
    campaign = await first_round(client, js, followups=plan, text="ann.lee@acmelabs.io,Ann Lee,Acme Labs\n")
    assert await engine.tick(js, now=at(DAY + 100)) == 0
    (r,) = await recipients(client, campaign["id"])
    assert r["followups_sent"] == 1 and "industry" in r["error"] and len(google.sent) == 1

    # A follow-up stuck in "sending" after a crash is skipped, never sent again.
    async with js.sessions() as session:
        await session.execute(update(Recipient).values(status="sending", followups_sent=0, updated_at=NOW - timedelta(minutes=30)))
        await session.commit()
    await engine.tick(js, now=at(DAY + 5000))
    (r,) = await recipients(client, campaign["id"])
    assert r["status"] == "sent" and r["followups_sent"] == 1 and "interrupted" in r["error"]


async def test_follow_up_plans_are_validated_previewed_and_editable(outreach):
    client, js = outreach
    body = {"name": "x", "window_start_hour": 0, "window_end_hour": 24}
    too_many = [{"days": 1, "body": "b"}] * 6
    assert (await client.post("/api/outreach/campaigns", json={**body, "followups": too_many})).status_code == 422
    assert (await client.post("/api/outreach/campaigns", json={**body, "followups": [{"days": 0, "body": "b"}]})).status_code == 422
    assert (await client.post("/api/outreach/campaigns", json={**body, "followups": [{"days": 1, "body": ""}]})).status_code == 422
    long_plan = [{"days": 40, "body": "b"}, {"days": 30, "body": "b"}]
    res = await client.post("/api/outreach/campaigns", json={**body, "followups": long_plan})
    assert res.status_code == 422 and "60 days" in res.text

    campaign = await make_campaign(client)
    cid = campaign["id"]
    await import_text(client, cid, "email,name,company\nann.lee@acmelabs.io,Ann Lee,Acme Labs\n")
    patched = await client.patch(f"/api/outreach/campaigns/{cid}", json={"followups": PLAN})
    assert [f["days"] for f in patched.json()["followups"]] == [3, 4]
    check = (await client.get(f"/api/outreach/campaigns/{cid}/check")).json()
    assert any("2 follow-up(s), 3, 4 day(s)" in w for w in check["warnings"])

    first = (await client.get(f"/api/outreach/campaigns/{cid}/preview")).json()
    one = (await client.get(f"/api/outreach/campaigns/{cid}/preview", params={"step": 1})).json()
    two = (await client.get(f"/api/outreach/campaigns/{cid}/preview", params={"step": 2})).json()
    assert one["subject"] == "Re: " + first["subject"] and "Acme Labs" in one["body"] and two["subject"] == "Last try, Ann"
    assert (await client.get(f"/api/outreach/campaigns/{cid}/preview", params={"step": 3})).status_code == 404

    # Changing the plan of a finished campaign reopens it, paused, so the user decides.
    async with js.sessions() as session:
        await session.execute(update(Campaign).values(status="completed"))
        await session.commit()
    again = await client.patch(f"/api/outreach/campaigns/{cid}", json={"followups": PLAN[:1]})
    assert again.json()["status"] == "paused"


def test_the_saved_signature_is_not_added_under_one_the_email_already_has():
    from app.jobs.schemas import JobSettings

    jobs = JobSettings(
        sender_name="Muhammad Adnan Amin",
        signature="Best Regards,\nMuhammad Adnan Amin\nadnanamin.available@gmail.com\nGithub: https://github.com/AdnanAmin045",
    )
    own = "Hello,\n\nMy pitch.\n\nYours sincerely,\nMuhammad Adnan Amin\nFull Stack Developer\nEmail: adnanamin.available@gmail.com"
    assert engine.with_signature(own, jobs) == own  # already signed: nothing is added

    plain = "Hello,\n\nMy pitch."
    assert engine.with_signature(plain, jobs).endswith("Github: https://github.com/AdnanAmin045")
    assert engine.with_signature(plain, jobs).count("Muhammad Adnan Amin") == 1
    assert engine.with_signature(plain, JobSettings()) == plain  # no signature saved
