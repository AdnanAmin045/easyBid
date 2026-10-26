"""Someone who answered is never followed up or written to again, wherever the answer came in."""

import httpx
from sqlalchemy import select, update

from app.jobs import followups as job_followups
from app.jobs.models import JobApplication
from app.models import utcnow
from app.outreach import engine
from app.outreach.models import Campaign, Recipient, RecipientStatus
from tests.test_followups import DAY, PLAN, first_round, thread_with  # noqa: F401
from tests.test_job_followups import PLAN as JOB_PLAN
from tests.test_job_followups import sent_application
from tests.test_jobs import JD, connect_gmail, jobs  # noqa: F401  (fixtures)
from tests.test_outreach import at, google, import_text, llm, make_campaign, outreach, recipients, sent_mail, start  # noqa: F401,F811

ANN = "ann.lee@acmelabs.io"


async def test_a_reply_in_a_new_conversation_stops_the_campaign_follow_up(outreach, google):
    client, js = outreach
    campaign = await first_round(client, js, followups=PLAN[:1], text=f"{ANN},Ann Lee,Acme Labs\nbob@globex.io,Bob Stone,Globex\n")
    # Ann answered, but from a fresh email instead of replying inside our thread.
    google.inbox.append({"id": "n1", "from": f"Ann Lee <{ANN}>"})
    sent = [await engine.tick(js, now=at(3 * DAY + 100 + i * 61)) for i in range(3)]
    assert sum(sent) == 1
    assert [m["To"] for m in sent_mail(google)[2:]] == ["bob@globex.io"]
    states = {r["email"]: r["status"] for r in await recipients(client, campaign["id"])}
    assert states == {ANN: "replied", "bob@globex.io": "sent"}


async def test_an_automatic_answer_in_the_inbox_is_not_a_reply(outreach, google):
    client, js = outreach
    await first_round(client, js, followups=PLAN[:1], text=f"{ANN},Ann Lee,Acme Labs\n")
    google.inbox.append({"id": "n1", "from": ANN, "auto": "auto-replied"})
    assert await engine.tick(js, now=at(3 * DAY + 100)) == 1


async def test_a_reply_to_another_campaign_stops_follow_ups_here(outreach, google):
    client, js = outreach
    campaign = await first_round(client, js, followups=PLAN[:1], text=f"{ANN},Ann Lee,Acme Labs\n")
    other = await make_campaign(client, name="Other")
    async with js.sessions() as session:
        session.add(Recipient(campaign_id=other["id"], position=1, email=ANN, status=RecipientStatus.REPLIED))
        await session.commit()
    assert await engine.tick(js, now=at(3 * DAY + 100)) == 0
    assert [r["status"] for r in await recipients(client, campaign["id"])] == ["replied"]
    assert len(google.sent) == 1


async def test_replied_addresses_are_held_back_even_outside_the_recent_window(outreach, google):
    client, js = outreach
    await first_round(client, js, followups=[], text=f"{ANN},Ann Lee,Acme Labs\n")
    async with js.sessions() as session:
        await session.execute(update(Recipient).values(status=RecipientStatus.REPLIED, sent_at=utcnow() - 400 * DAY_TD))
        await session.commit()
    second = await make_campaign(client, name="Second")
    res = await import_text(client, second["id"], f"{ANN},Ann Lee,Acme Labs\nnew@globex.io,New,Globex")
    assert res["held_back"] == 1
    held = next(r for r in await recipients(client, second["id"]) if r["email"] == ANN)
    assert held["status"] == "skipped" and "replied" in held["error"]

    # Imported without the check, it is still stopped when its turn comes.
    third = await make_campaign(client, name="Third")
    assert (await import_text(client, third["id"], ANN, skip_recent=False))["held_back"] == 0
    await start(client, third["id"])
    assert await engine.tick(js, now=at(10 * DAY)) == 0
    stopped = (await recipients(client, third["id"]))[0]
    assert stopped["status"] == "skipped" and "replied" in stopped["error"]


async def test_job_follow_up_stops_when_the_address_wrote_in_a_new_conversation(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js)
    google.inbox.append({"id": "n1", "from": "Careers <careers@acmelabs.io>"})
    now = utcnow()
    assert await job_followups.tick(js, now=now + 6 * DAY_TD) == 0
    state = (await client.get(f"/api/jobs/applications/{app['id']}")).json()
    assert state["outcome"] == "replied" and len(google.sent) == 1


async def test_job_follow_up_stops_when_a_campaign_recipient_replied(jobs, google):
    client, js = jobs
    app = await sent_application(client, google, js)
    campaign = await make_campaign(client)
    async with js.sessions() as session:
        session.add(Recipient(campaign_id=campaign["id"], position=1, email="careers@acmelabs.io", status=RecipientStatus.REPLIED))
        await session.commit()
    assert await job_followups.tick(js, now=utcnow() + 6 * DAY_TD) == 0
    assert (await client.get(f"/api/jobs/applications/{app['id']}")).json()["outcome"] == "replied" and len(google.sent) == 1


async def test_jobs_warns_about_addresses_a_campaign_wrote_to_or_that_replied(jobs, google):
    client, js = jobs
    await connect_gmail(client)
    campaign = await make_campaign(client)
    async with js.sessions() as session:
        session.add(Recipient(campaign_id=campaign["id"], position=1, email="careers@acmelabs.io", status=RecipientStatus.SENT, sent_at=utcnow()))
        await session.commit()
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    assert {e["email"]: e["applied_before"] is not None for e in details["emails"]}["careers@acmelabs.io"]

    draft = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})).json()
    blocked = await client.post(f"/api/jobs/applications/{draft['id']}/send", json={})
    assert blocked.status_code == 409 and blocked.json()["detail"].startswith("duplicate: an outreach campaign")
    assert not google.sent
    sent = await client.post(f"/api/jobs/applications/{draft['id']}/send", json={"allow_duplicate": True})
    assert sent.status_code == 200 and len(google.sent) == 1

    # An address that answered is flagged even when nothing was sent to it recently.
    async with js.sessions() as session:
        await session.execute(update(Recipient).values(status=RecipientStatus.REPLIED, sent_at=utcnow() - 400 * DAY_TD))
        await session.execute(update(JobApplication).values(sent_at=utcnow() - 400 * DAY_TD))
        await session.commit()
    again = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})).json()
    res = await client.post(f"/api/jobs/applications/{again['id']}/send", json={})
    assert res.status_code == 409 and "already replied" in res.json()["detail"]


from datetime import timedelta  # noqa: E402

DAY_TD = timedelta(days=1)
