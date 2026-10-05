"""Write an application email from the job description, the user's profile and their prompt."""

import json
import re

from app.jobs.extract import DATA_GUARD
from app.jobs.models import JobProfileItem, JobResume
from app.jobs.schemas import Extraction, JobSettings
from app.services.llm import LLM, LLMError, clean_proposal

DEFAULT_PROMPT = """You write job application emails for a software developer.

- First person, plain and confident. No greeting clichés such as "I hope this email finds you well".
- Open with the role and why this candidate fits it, in one or two sentences.
- Match two or three of the job's requirements with concrete experience from the profile.
- Mention that the CV is attached when one is attached.
- Close with one line asking for a conversation.
- Keep it short: a busy recruiter should read it in under a minute."""

EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string", "description": "Email subject line."},
        "body": {"type": "string", "description": "Email body from the greeting to the closing line, without a signature."},
    },
    "required": ["subject", "body"],
    "additionalProperties": False,
}

PLACEHOLDER = re.compile(r"\[[^\]\n]{1,40}\]|\{\{?[^}\n]{1,30}\}?\}|<[A-Z][A-Za-z ]{1,30}>")


def profile_block(items: list[JobProfileItem]) -> str:
    lines = [f"[{i.kind}] {i.title}" + (f": {i.content}" if i.content else "") for i in items]
    return "<candidate_profile>\n" + ("\n".join(lines) or "(empty)") + "\n</candidate_profile>"


def job_block(source_text: str, details: Extraction) -> str:
    known = {
        "Company": details.company,
        "Role": details.role,
        "Location": details.location,
        "Work mode": details.work_mode,
        "Addressed to": details.recipient_name,
        "Required skills": ", ".join(details.required_skills),
        "Deadline": details.deadline,
    }
    facts = "\n".join(f"{k}: {v}" for k, v in known.items() if v)
    instructions = "\n".join(f"- {i}" for i in details.apply_instructions) or "- none"
    return (
        f"<job_description>\n{source_text}\n</job_description>\n\n"
        f"<job_facts>\n{facts}\n</job_facts>\n\n"
        f"<application_instructions>\n{instructions}\n</application_instructions>"
    )


def email_problem(subject: str, body: str, s: JobSettings) -> str | None:
    if not subject.strip():
        return "missing a subject"
    if len(body) < s.email_min_chars:
        return f"too short: {len(body)} characters, minimum is {s.email_min_chars}"
    if len(body) > s.email_max_chars:
        return f"too long: {len(body)} characters, maximum is {s.email_max_chars}"
    for text in (subject, body):
        found = PLACEHOLDER.search(text)
        if found:
            return f"contains an unfilled placeholder: {found.group(0)}"
    return None


def with_signature(body: str, s: JobSettings) -> str:
    signature = s.signature.strip() or s.sender_name.strip()
    return f"{body.rstrip()}\n\n{signature}" if signature else body.rstrip()


async def write_email(
    llm: LLM,
    prompt: str,
    source_text: str,
    details: Extraction,
    profile: list[JobProfileItem],
    resume: JobResume | None,
    s: JobSettings,
) -> tuple[str, str]:
    """Returns (subject, body). The body ends with the signature from settings."""
    system = (
        f"{prompt}\n\n{DATA_GUARD}\n\n"
        "Rules:\n"
        "- Follow every item in <application_instructions> (required subject text, reference codes, questions).\n"
        "- Where the instructions ask for the candidate's name, use 'Candidate name'; if none is given, leave the name out.\n"
        "- Only claim skills and experience that appear in <candidate_profile>. Never invent employers, dates or numbers.\n"
        "- Address the person in 'Addressed to' by name if given, otherwise use a neutral greeting.\n"
        "- Plain text: no markdown, no bullet symbols, no placeholders such as [Company].\n"
        "- Do not add a signature; it is appended automatically.\n"
        f"- Body between {s.email_min_chars} and {s.email_max_chars} characters."
    )
    attachment = f"A CV is attached: {resume.filename}." if resume else "No CV is attached."
    name = f"Candidate name: {s.sender_name.strip()}\n\n" if s.sender_name.strip() else ""
    user = f"{name}{profile_block(profile)}\n\n{job_block(source_text, details)}\n\n{attachment}"

    subject = body = ""
    problem = None
    for _ in range(2):
        raw = await llm.complete(model=s.model, system=system, user=user, schema=EMAIL_SCHEMA)
        try:
            data = json.loads(raw)
            subject = " ".join(str(data["subject"]).split())[:300]
            body = clean_proposal(str(data["body"]))
        except (ValueError, KeyError, TypeError) as e:
            raise LLMError(f"The model's answer was not valid JSON: {raw[:200]}") from e
        problem = email_problem(subject, body, s)
        if problem is None:
            return subject, with_signature(body, s)
        user += f"\n\nYour previous draft was {problem}. Write it again following the rules."
    raise LLMError(f"Email rejected: {problem}")
