from datetime import timedelta

from app.jobs import followups as job_followups
from app.models import utcnow
from app.outreach import engine
from tests.test_jobs import JD, connect_gmail, jobs  # noqa: F401  (fixtures)
from tests.test_job_followups import mails as job_mails
from tests.test_outreach import at, google, import_text, llm, make_campaign, outreach, sent_mail, start  # noqa: F401

PDF = b"%PDF-1.4 fake cv"
DAY = 86400


async def upload_cv(client) -> int:
    res = await client.post("/api/jobs/resumes", files={"file": ("adnan-cv.pdf", PDF, "application/pdf")}, data={"name": "CV"})
    assert res.status_code == 200, res.text
    return res.json()["id"]


def names(mail) -> list[str]:
    return [part.get_filename() for part in mail.iter_attachments()]


def step(attach: bool, days: int = 3) -> dict:
    return {"days": days, "subject": "", "body": "Following up on my earlier note, thank you.", "attach_resume": attach}


async def test_campaign_attaches_the_cv_to_the_first_email_and_to_chosen_follow_ups(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    cv = await upload_cv(client)
    campaign = await make_campaign(client, resume_id=cv, followups=[step(True, 2), step(False, 2)])
    await import_text(client, campaign["id"], "ann.lee@acmelabs.io,Ann Lee,Acme Labs\n".replace("ann", "email,name,company\nann", 1))
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(0)) == 1
    assert await engine.tick(js, now=at(2 * DAY + 100)) == 1
    assert await engine.tick(js, now=at(4 * DAY + 300)) == 1
    first, one, two = sent_mail(google)
    assert names(first) == ["adnan-cv.pdf"]  # the first email carries it
    assert names(one) == ["adnan-cv.pdf"]  # follow-up 1 was set to carry it too
    assert names(two) == []  # follow-up 2 was not


async def test_the_first_email_can_go_without_the_cv_while_a_follow_up_carries_it(outreach, google):
    client, js = outreach
    await connect_gmail(client)
    cv = await upload_cv(client)
    campaign = await make_campaign(client, resume_id=cv, attach_first=False, followups=[step(True, 1)])
    await import_text(client, campaign["id"], "email,name,company\nann.lee@acmelabs.io,Ann Lee,Acme Labs\n")
    await start(client, campaign["id"])
    assert await engine.tick(js, now=at(0)) == 1
    assert await engine.tick(js, now=at(DAY + 100)) == 1
    first, one = sent_mail(google)
    assert names(first) == [] and names(one) == ["adnan-cv.pdf"]

    # The test email follows the same switch.
    other = await make_campaign(client, name="Test", resume_id=cv, attach_first=False)
    await import_text(client, other["id"], "email,name\nbob@globex.io,Bob\n")
    await client.post(f"/api/outreach/campaigns/{other['id']}/test-send", json={})
    assert names(sent_mail(google)[-1]) == []


async def test_a_follow_up_that_needs_the_cv_blocks_the_start_when_none_is_chosen(outreach):
    client, _ = outreach
    await connect_gmail(client)
    campaign = await make_campaign(client, followups=[step(True)])
    await import_text(client, campaign["id"], "ann.lee@acmelabs.io")
    res = await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")
    assert res.status_code == 409 and "should carry the CV" in res.text
    cv = await upload_cv(client)
    await client.patch(f"/api/outreach/campaigns/{campaign['id']}", json={"resume_id": cv})
    assert (await client.post(f"/api/outreach/campaigns/{campaign['id']}/start")).status_code == 200


async def test_job_application_follow_up_can_carry_the_application_cv(jobs, google):
    client, js = jobs
    await connect_gmail(client)
    cv = await upload_cv(client)
    details = (await client.post("/api/jobs/extract", json={"text": JD})).json()
    app = (await client.post("/api/jobs/applications", json={"source_text": JD, "details": details, "to_email": "careers@acmelabs.io", "resume_id": cv})).json()
    plan = [step(True, 5), step(False, 3)]
    assert (await client.put(f"/api/jobs/applications/{app['id']}/followups", json={"followups": plan})).json()["followups"][0]["attach_resume"] is True
    assert (await client.post(f"/api/jobs/applications/{app['id']}/send", json={})).status_code == 200

    start_time = utcnow()
    assert await job_followups.tick(js, now=start_time + 5 * DAY_TD + timedelta(minutes=1)) == 1
    assert await job_followups.tick(js, now=start_time + 8 * DAY_TD + timedelta(minutes=5)) == 1
    first, one, two = job_mails(google)
    assert names(first) == ["adnan-cv.pdf"] and names(one) == ["adnan-cv.pdf"] and names(two) == []


DAY_TD = timedelta(days=1)
