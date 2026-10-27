"""A mailbox that is not Gmail (Hostinger, say): sent over SMTP, answers read over IMAP."""

import imaplib
import smtplib
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from app.jobs import followups as job_followups
from app.models import utcnow
from app.outreach import engine
from app.outreach.models import Campaign, Recipient, Suppression
from tests.test_followups import DAY, PLAN  # noqa: F401
from tests.test_job_followups import PLAN as JOB_PLAN
from tests.test_jobs import JD, jobs  # noqa: F401  (fixtures)
from tests.test_outreach import at, google, import_text, llm, make_campaign, outreach, recipients, start  # noqa: F401

BOX = "adnan@codevryn.com"
FORM = {
    "email": BOX,
    "smtp_host": "smtp.hostinger.com",
    "smtp_port": 465,
    "smtp_secure": True,
    "smtp_user": "",
    "smtp_password": "mailbox-password",
    "imap_host": "imap.hostinger.com",
    "imap_port": 993,
    "sender_name": "Adnan Codevryn",
    "signature": "Adnan\nCodevryn",
}


class World:
    """A pretend mail server: what was sent over SMTP and what sits in the IMAP inbox."""

    def __init__(self):
        self.sent = []
        self.inbox: list[dict] = []  # uid, from, auto, references, in_reply_to, text, date
        self.auth_ok = True
        self.imap_ok = True
        self.send_error: Exception | None = None
        self.logins = []
        world = self

        class SMTP:
            def __init__(self, host, port, timeout=None, context=None):
                world.logins.append((host, port))

            def ehlo(self):
                pass

            def starttls(self, context=None):
                pass

            def login(self, user, password):
                world.logins.append((user, password))
                if not world.auth_ok:
                    raise smtplib.SMTPAuthenticationError(535, b"5.7.8 Authentication failed")

            def send_message(self, message):
                if world.send_error:
                    raise world.send_error
                world.sent.append(message)

            def quit(self):
                pass

        class IMAP:
            def __init__(self, host, port, timeout=None, ssl_context=None):
                world.logins.append((host, port))

            def login(self, user, password):
                if not world.imap_ok:
                    raise imaplib.IMAP4.error("LOGIN failed")

            def select(self, name, readonly=False):
                return "OK", [b"1"]

            def uid(self, command, *args):
                if command == "SEARCH":
                    criteria = " ".join(args[1:])
                    hits = world.matching(criteria)
                    return "OK", [b" ".join(str(m["uid"]).encode() for m in hits)]
                message = next(m for m in world.inbox if m["uid"] == int(args[0]))
                headers = f"From: {message['from']}\r\n" + (f"Auto-Submitted: {message['auto']}\r\n" if message.get("auto") else "") + "\r\n"
                stamp = message["date"].strftime("%d-%b-%Y %H:%M:%S +0000")
                head = f'{message["uid"]} (UID {message["uid"]} INTERNALDATE "{stamp}" BODY[HEADER.FIELDS (FROM AUTO-SUBMITTED)] {{{len(headers)}}}'.encode()
                return "OK", [(head, headers.encode()), b")"]

            def logout(self):
                pass

        self.SMTP, self.IMAP = SMTP, IMAP

    def matching(self, criteria: str) -> list[dict]:
        def quoted(after: str) -> str:
            return criteria.split(after, 1)[1].split('"')[1]

        if criteria.startswith("OR HEADER References"):
            wanted = quoted("References")
            return [m for m in self.inbox if wanted in m.get("references", "") or wanted in m.get("in_reply_to", "")]
        if criteria.startswith("TEXT"):
            wanted = quoted("TEXT")
            return [m for m in self.inbox if wanted in m.get("text", "") and ("mailer-daemon" in m["from"] or "postmaster" in m["from"])]
        if criteria.startswith("FROM"):
            return [m for m in self.inbox if quoted("FROM").lower() in m["from"].lower()]
        return []

    def reply(self, **fields):
        self.inbox.append({"uid": len(self.inbox) + 1, "date": datetime.now(timezone.utc) + timedelta(days=30), **fields})


def plug(js) -> World:
    world = World()
    js.smtp.smtp_ssl, js.smtp.smtp_plain, js.smtp.imap_ssl = world.SMTP, world.SMTP, world.IMAP
    return world


async def add_mailbox(client, **changes) -> dict:
    res = await client.post("/api/jobs/gmail/smtp", json={**FORM, **changes})
    assert res.status_code == 200, res.text
    return res.json()


async def test_a_smtp_mailbox_is_checked_then_saved_without_exposing_its_password(outreach, google):
    client, js = outreach
    world = plug(js)
    world.auth_ok = False
    refused = await client.post("/api/jobs/gmail/smtp", json=FORM)
    assert refused.status_code == 422 and "login refused" in refused.json()["detail"]
    assert (await client.get("/api/jobs/gmail")).json()["accounts"] == []  # nothing is saved when the login fails

    world.auth_ok, world.imap_ok = True, False
    assert "IMAP login refused" in (await client.post("/api/jobs/gmail/smtp", json=FORM)).json()["detail"]
    world.imap_ok = True
    bad = await client.post("/api/jobs/gmail/smtp", json={**FORM, "smtp_host": "https://smtp.hostinger.com:465"})
    assert bad.status_code == 422

    account = await add_mailbox(client)
    assert account["kind"] == "smtp" and account["is_default"] and account["smtp_host"] == "smtp.hostinger.com"
    assert "mailbox-password" not in (await client.get("/api/jobs/gmail")).text
    async with js.sessions() as session:
        from app.jobs.models import GmailAccount

        stored = (await session.scalars(select(GmailAccount))).one()
    assert "mailbox-password" not in stored.smtp_password and stored.smtp_user == BOX

    # Adding it again renews it instead of making a copy.
    await add_mailbox(client, smtp_password="new-password")
    assert len((await client.get("/api/jobs/gmail")).json()["accounts"]) == 1
    assert (await client.post(f"/api/jobs/gmail/{account['id']}/disconnect")).status_code == 204


async def test_a_campaign_sends_and_follows_up_over_smtp_and_stops_at_a_reply(outreach, google):
    client, js = outreach
    world = plug(js)
    account = await add_mailbox(client)
    campaign = await make_campaign(client, followups=PLAN[:1], gmail_account_id=account["id"])
    await import_text(client, campaign["id"], "email,name,company\nann@acmelabs.io,Ann Lee,Acme\nbob@globex.io,Bob Stone,Globex\ncarol@initech.io,Carol,Initech")
    await start(client, campaign["id"])
    for i in range(3):
        assert await engine.tick(js, now=at(i * 61)) == 1
    assert [m["To"] for m in world.sent] == ["ann@acmelabs.io", "bob@globex.io", "carol@initech.io"]
    assert BOX in world.sent[0]["From"] and "Adnan Codevryn" in world.sent[0]["From"]
    assert world.sent[0].get_content().rstrip().endswith("Codevryn")  # the mailbox's own signature
    assert not google.sent  # nothing went through Gmail

    async with js.sessions() as session:
        rows = {r.email: r for r in await session.scalars(select(Recipient))}
    assert rows["ann@acmelabs.io"].gmail_thread_id == str(world.sent[0]["Message-ID"])

    # Bob answered inside the conversation, Carol wrote separately, an out-of-office does not count.
    world.reply(**{"from": "Bob Stone <bob@globex.io>", "references": str(world.sent[1]["Message-ID"])})
    world.reply(**{"from": "carol@initech.io", "references": ""})
    world.reply(**{"from": "ann@acmelabs.io", "auto": "auto-replied", "references": ""})
    sent = [await engine.tick(js, now=at(3 * DAY + 100 + i * 61)) for i in range(3)]
    assert sum(sent) == 1
    follow = world.sent[3]
    assert follow["To"] == "ann@acmelabs.io" and follow["In-Reply-To"] == world.sent[0]["Message-ID"]
    assert follow["Subject"].startswith("Re: ")
    states = {r["email"]: r["status"] for r in await recipients(client, campaign["id"])}
    assert states == {"ann@acmelabs.io": "sent", "bob@globex.io": "replied", "carol@initech.io": "replied"}


async def test_a_bounce_in_the_inbox_marks_the_recipient_and_blocks_the_address(outreach, google):
    client, js = outreach
    world = plug(js)
    account = await add_mailbox(client)
    campaign = await make_campaign(client, gmail_account_id=account["id"])
    await import_text(client, campaign["id"], "dead@nowhere.io")
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(1)) == 1
    world.reply(**{"from": "Mail Delivery Subsystem <mailer-daemon@hostinger.com>", "text": f"could not deliver {world.sent[0]['Message-ID']}"})
    await engine.tick(js, now=at(20 * 60))
    assert (await recipients(client, campaign["id"]))[0]["status"] == "bounced"
    async with js.sessions() as session:
        assert [s.email for s in await session.scalars(select(Suppression))] == ["dead@nowhere.io"]


async def test_smtp_failures_are_told_apart(outreach, google):
    client, js = outreach
    world = plug(js)
    account = await add_mailbox(client)
    campaign = await make_campaign(client, gmail_account_id=account["id"])
    await import_text(client, campaign["id"], "a@acmelabs.io\nb@acmelabs.io\nc@acmelabs.io")
    await start(client, campaign["id"])

    # The server refuses one address for good: that recipient fails, the campaign goes on.
    world.send_error = smtplib.SMTPRecipientsRefused({"a@acmelabs.io": (550, b"5.1.1 no such user")})
    assert await engine.tick(js, now=at(1)) == 0
    first = (await recipients(client, campaign["id"]))[0]
    assert first["status"] == "failed" and "refused the recipient" in first["error"] and first["attempts"] == 1

    # A connection that breaks mid-send is never repeated: it may have gone.
    world.send_error = smtplib.SMTPServerDisconnected("Connection unexpectedly closed")
    assert await engine.tick(js, now=at(100)) == 0
    second = (await recipients(client, campaign["id"]))[1]
    assert second["status"] == "failed" and "Outcome unknown" in second["error"]

    # The mail server asks us to slow down: the campaign pauses and the recipient stays queued.
    world.send_error = smtplib.SMTPResponseException(451, b"4.7.1 hourly sending limit reached")
    assert await engine.tick(js, now=at(200)) == 0
    state = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert state["status"] == "paused" and "limited by its mail server" in state["pause_reason"]
    assert (await recipients(client, campaign["id"]))[2]["status"] == "pending"

    # A wrong password pauses everything and says which mailbox to fix.
    world.send_error = None
    world.auth_ok = False
    async with js.sessions() as session:
        await session.execute(update(Campaign).values(status="running", pause_reason="", next_send_at=None))
        await session.commit()
    assert await engine.tick(js, now=at(400)) == 0
    state = (await client.get(f"/api/outreach/campaigns/{campaign['id']}")).json()
    assert state["status"] == "paused" and "Email settings" in state["pause_reason"] and BOX in state["pause_reason"]


async def test_an_application_goes_out_over_smtp_and_is_followed_up_there(jobs, google):
    client, js = jobs
    world = plug(js)
    account = await add_mailbox(client)
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    draft = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io"})).json()
    await client.put(f"/api/jobs/applications/{draft['id']}/followups", json={"followups": JOB_PLAN[:1]})
    sent = await client.post(f"/api/jobs/applications/{draft['id']}/send", json={"gmail_account_id": account["id"]})
    assert sent.status_code == 200 and sent.json()["gmail_account_id"] == account["id"]
    assert BOX in world.sent[0]["From"] and sent.json()["gmail_thread_id"] == str(world.sent[0]["Message-ID"])

    assert await job_followups.tick(js, now=utcnow() + timedelta(days=6)) == 1
    assert world.sent[1]["In-Reply-To"] == world.sent[0]["Message-ID"] and not google.sent
