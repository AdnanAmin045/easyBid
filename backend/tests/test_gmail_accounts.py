"""Several Gmail accounts: each campaign and application picks one, and everything that follows stays on it."""

from datetime import timedelta

from sqlalchemy import select, update

from app.jobs import followups as job_followups
from app.jobs.models import GmailAccount
from app.models import utcnow
from app.outreach import engine
from app.outreach.models import Campaign, Recipient
from tests.test_followups import DAY, PLAN, thread_with  # noqa: F401
from tests.test_job_followups import PLAN as JOB_PLAN
from tests.test_job_followups import sent_application
from tests.test_jobs import JD, connect_gmail, jobs  # noqa: F401  (fixtures)
from tests.test_outreach import (  # noqa: F401  (fixtures)
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

WORK = "work@company.io"


async def connect_second(client, google, email=WORK, refresh="rt-work") -> dict:
    google.next_email, google.next_refresh = email, refresh
    await connect_gmail(client)
    google.next_email, google.next_refresh = "me@gmail.com", "rt-secret"
    status = (await client.get("/api/jobs/gmail")).json()
    return next(a for a in status["accounts"] if a["email"] == email)


async def test_several_gmail_accounts_can_be_connected_and_managed(jobs, google):
    client, js = jobs
    await connect_gmail(client)
    work = await connect_second(client, google)
    status = (await client.get("/api/jobs/gmail")).json()
    assert [(a["email"], a["is_default"]) for a in status["accounts"]] == [("me@gmail.com", True), (WORK, False)]
    assert status["email"] == "me@gmail.com"

    # Connecting an address again renews it instead of adding a copy.
    await connect_second(client, google)
    assert len((await client.get("/api/jobs/gmail")).json()["accounts"]) == 2

    saved = await client.patch(f"/api/jobs/gmail/{work['id']}", json={"sender_name": "Work Me", "signature": "Work Me, CTO"})
    assert saved.json()["sender_name"] == "Work Me"
    made = await client.post(f"/api/jobs/gmail/{work['id']}/default")
    assert made.json()["is_default"] and (await client.get("/api/jobs/gmail")).json()["email"] == WORK

    # Removing the default hands the role to the one that is left.
    assert (await client.post(f"/api/jobs/gmail/{work['id']}/disconnect")).status_code == 204
    left = (await client.get("/api/jobs/gmail")).json()
    assert [(a["email"], a["is_default"]) for a in left["accounts"]] == [("me@gmail.com", True)]
    assert (await client.post("/api/jobs/gmail/999/disconnect")).status_code == 404


async def test_each_campaign_sends_from_its_own_gmail_and_follows_up_from_the_same_one(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    work = await connect_second(client, google)
    await client.put("/api/jobs/settings", json={"sender_name": "Adnan Amin", "signature": "Adnan Amin\nFull-stack developer"})
    await client.patch(f"/api/jobs/gmail/{work['id']}", json={"sender_name": "Ada Work", "signature": "Ada Work\nCTO"})

    personal = await make_campaign(client, name="Personal", followups=PLAN[:1])
    business = await make_campaign(client, name="Business", followups=PLAN[:1], gmail_account_id=work["id"])
    assert business["gmail_account_id"] == work["id"] and personal["gmail_account_id"] is None
    await import_text(client, personal["id"], "email,name,company\nann@acmelabs.io,Ann Lee,Acme")
    await import_text(client, business["id"], "email,name,company\nbob@globex.io,Bob Stone,Globex")
    await start(client, personal["id"])
    await start(client, business["id"])

    assert await engine.tick(js, now=at(1)) == 2  # one email per Gmail account in the same pass
    first = {m["To"]: m for m in sent_mail(google)}
    assert "me@gmail.com" in first["ann@acmelabs.io"]["From"] and first["ann@acmelabs.io"].get_content().rstrip().endswith("Full-stack developer")
    assert WORK in first["bob@globex.io"]["From"] and first["bob@globex.io"].get_content().rstrip().endswith("CTO")
    assert sorted(google.sent_with) == ["at-rt-secret", "at-rt-work"]

    async with js.sessions() as session:
        owners = {r.email: r.gmail_account_id for r in await session.scalars(select(Recipient))}
        accounts = {a.email: a.id for a in await session.scalars(select(GmailAccount))}
    assert owners == {"ann@acmelabs.io": accounts["me@gmail.com"], "bob@globex.io": accounts[WORK]}

    # The business campaign is switched to the personal Gmail, but Bob's conversation lives in the work mailbox.
    await client.patch(f"/api/outreach/campaigns/{business['id']}", json={"gmail_account_id": accounts["me@gmail.com"]})
    google.sent_with.clear()
    assert sum([await engine.tick(js, now=at(3 * DAY + 100 + i * 61)) for i in range(3)]) == 2
    assert sorted(google.sent_with) == ["at-rt-secret", "at-rt-work"]
    followups = {m["To"]: m for m in sent_mail(google)[2:]}
    assert WORK in followups["bob@globex.io"]["From"]


async def test_limits_are_counted_for_each_gmail_on_its_own(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    work = await connect_second(client, google)
    await client.put("/api/outreach/settings", json={"daily_limit": 1, "min_gap_seconds": 5, "skip_recent_days": 30, "bounce_pause_percent": 8, "model": "gemini-3.5-flash"})
    one = await make_campaign(client, name="One")
    two = await make_campaign(client, name="Two", gmail_account_id=work["id"])
    await import_text(client, one["id"], "a@acmelabs.io\nb@acmelabs.io")
    await import_text(client, two["id"], "c@globex.io\nd@globex.io")
    await start(client, one["id"])
    await start(client, two["id"])
    sent = [await engine.tick(js, now=at(i * 61)) for i in range(4)]
    # The limit is one a day per Gmail: each campaign sent one, the second of each waits.
    assert sum(sent) == 2 and sorted(m["To"] for m in sent_mail(google)) == ["a@acmelabs.io", "c@globex.io"]
    state = (await client.get(f"/api/outreach/campaigns/{one['id']}")).json()
    assert "Account limit reached" in state["waiting"] and "me@gmail.com" in state["waiting"]


async def test_disconnecting_a_gmail_stops_what_depends_on_it(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    work = await connect_second(client, google)
    campaign = await make_campaign(client, followups=PLAN[:1], gmail_account_id=work["id"])
    await import_text(client, campaign["id"], "ann@acmelabs.io")
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(1)) == 1

    assert (await client.post(f"/api/jobs/gmail/{work['id']}/disconnect")).status_code == 204
    # The campaign that used it stops, rather than quietly carrying on from another Gmail.
    paused = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert paused["status"] == "paused" and WORK in paused["waiting"]

    # Its conversations are out of reach, so no follow-up is sent from somewhere else.
    async with js.sessions() as session:
        await session.execute(update(Campaign).where(Campaign.id == campaign["id"]).values(status="running", pause_reason=""))
        await session.commit()
    assert await engine.tick(js, now=at(3 * DAY + 100)) == 0
    assert len(google.sent) == 1
    assert "no longer connected" in (await recipients(client, campaign["id"]))[0]["error"]
    assert (await client.post("/api/outreach/campaigns", json={"name": "x", "subject_template": "s", "body_template": "b", "gmail_account_id": 999})).status_code == 404


async def test_an_application_is_sent_from_the_chosen_gmail_and_followed_up_from_it(jobs, google):
    client, js = jobs
    await connect_gmail(client)
    work = await connect_second(client, google)
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    draft = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})).json()
    await client.put(f"/api/jobs/applications/{draft['id']}/followups", json={"followups": JOB_PLAN[:1]})
    sent = await client.post(f"/api/jobs/applications/{draft['id']}/send", json={"gmail_account_id": work["id"]})
    assert sent.status_code == 200 and sent.json()["gmail_account_id"] == work["id"]
    assert google.sent_with == ["at-rt-work"]

    assert await job_followups.tick(js, now=utcnow() + timedelta(days=6)) == 1
    assert google.sent_with == ["at-rt-work", "at-rt-work"]


ALIAS = "adnan@codevryn.com"


async def test_a_verified_send_as_address_becomes_a_sender_through_its_gmail(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    gmail = (await client.get("/api/jobs/gmail")).json()["accounts"][0]
    google.send_as = [(ALIAS, "accepted"), ("pending@codevryn.com", "pending")]

    listed = (await client.get(f"/api/jobs/gmail/{gmail['id']}/send-as")).json()
    assert {(a["email"], a["verified"], a["added"]) for a in listed} == {(ALIAS, True, False), ("pending@codevryn.com", False, False)}  # the primary is not offered

    assert (await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": "other@codevryn.com"})).status_code == 422  # not in Gmail's list
    unverified = await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": "pending@codevryn.com"})
    assert unverified.status_code == 422 and "not verified" in unverified.json()["detail"]

    added = await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": ALIAS})
    assert added.status_code == 200 and added.json()["kind"] == "alias" and added.json()["parent_id"] == gmail["id"]
    assert added.json()["sender_name"] == "Adnan Codevryn" and not added.json()["is_default"]
    again = await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": ALIAS})
    assert again.json()["id"] == added.json()["id"] and len((await client.get("/api/jobs/gmail")).json()["accounts"]) == 2


async def test_a_campaign_sends_as_the_alias_through_gmail_and_shares_the_gmails_limits(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    gmail = (await client.get("/api/jobs/gmail")).json()["accounts"][0]
    google.send_as = [(ALIAS, "accepted")]
    alias = (await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": ALIAS})).json()
    await client.put("/api/outreach/settings", json={"daily_limit": 1, "min_gap_seconds": 5, "skip_recent_days": 30, "bounce_pause_percent": 8, "model": "gemini-3.5-flash"})

    business = await make_campaign(client, name="Business", followups=PLAN[:1], gmail_account_id=alias["id"])
    personal = await make_campaign(client, name="Personal", gmail_account_id=gmail["id"])
    await import_text(client, business["id"], "ann@acmelabs.io")
    await import_text(client, personal["id"], "bob@globex.io")
    await start(client, business["id"])
    await start(client, personal["id"])
    sent = [await engine.tick(js, now=at(i * 61)) for i in range(3)]
    # One Gmail, one daily limit: the alias and the Gmail itself share it.
    assert sum(sent) == 1
    mail = sent_mail(google)[0]
    assert ALIAS in mail["From"] and "me@gmail.com" not in mail["From"]
    assert google.sent_with == ["at-rt-secret"]  # sent through the Gmail connection, over HTTPS

    async with js.sessions() as session:
        owner = (await session.scalars(select(Recipient).where(Recipient.gmail_account_id == alias["id"]))).one()
    assert owner.email == "ann@acmelabs.io"

    # The follow-up goes from the alias too, in the same thread.
    await client.put("/api/outreach/settings", json={"daily_limit": 50, "min_gap_seconds": 5, "skip_recent_days": 30, "bounce_pause_percent": 8, "model": "gemini-3.5-flash"})
    assert sum([await engine.tick(js, now=at(3 * DAY + 100 + i * 61)) for i in range(3)]) >= 1
    follow = [m for m in sent_mail(google) if m["To"] == "ann@acmelabs.io"][-1]
    assert ALIAS in follow["From"] and follow["In-Reply-To"] == mail["Message-ID"]


async def test_removing_an_alias_or_its_gmail(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    gmail = (await client.get("/api/jobs/gmail")).json()["accounts"][0]
    google.send_as = [(ALIAS, "accepted")]
    alias = (await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": ALIAS})).json()
    campaign = await make_campaign(client, gmail_account_id=alias["id"])
    await import_text(client, campaign["id"], "ann@acmelabs.io")
    await start(client, campaign["id"])

    assert (await client.post(f"/api/jobs/gmail/{alias['id']}/disconnect")).status_code == 204
    assert [a["email"] for a in (await client.get("/api/jobs/gmail")).json()["accounts"]] == ["me@gmail.com"]
    assert not google.revoked  # the Gmail itself stays connected
    assert (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()["status"] == "paused"

    await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": ALIAS})
    assert (await client.post(f"/api/jobs/gmail/{gmail['id']}/disconnect")).status_code == 204
    assert (await client.get("/api/jobs/gmail")).json()["accounts"] == []  # the alias goes with its Gmail


async def test_an_unused_smtp_mailbox_for_the_same_address_is_turned_into_the_alias(outreach, google):
    from tests.test_smtp_accounts import add_mailbox, plug

    client, js = outreach
    plug(js)
    await connect_gmail(client)
    gmail = next(a for a in (await client.get("/api/jobs/gmail")).json()["accounts"])
    smtp = await add_mailbox(client)
    campaign = await make_campaign(client, gmail_account_id=smtp["id"])
    google.send_as = [(ALIAS, "accepted")]

    converted = await client.post(f"/api/jobs/gmail/{gmail['id']}/aliases", json={"email": ALIAS})
    assert converted.json()["id"] == smtp["id"] and converted.json()["kind"] == "alias"  # the campaign keeps pointing at it
    assert (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()["gmail_account_id"] == smtp["id"]
    async with js.sessions() as session:
        stored = await session.get(GmailAccount, smtp["id"])
    assert stored.smtp_password == "" and stored.smtp_host == ""
