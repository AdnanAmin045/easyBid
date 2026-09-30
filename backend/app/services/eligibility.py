"""Can this account bid on this project at all? Checked before any AI call.

Only requirements that are visible up front are checked here (Preferred Freelancer only, identity
verification, bids left). Others Freelancer reveals only by refusing the bid, such as a minimum account
balance. Those cannot be predicted from the project (bids in the same currency have gone both ways), so
such a project is attempted and the pipeline moves on if the bid is refused.
"""

from datetime import timedelta

from app.models import Project, utcnow

# Refusals about one project's own requirements (such as a minimum account balance), not about the account.
PROJECT_REQUIREMENT_CODES = ("BID_MINIMUM_REQUIREMENT_NOT_MET",)

# After this many refused bids in a row, hold off for a while and then carry on by itself.
# A single refusal never stops anything: the pipeline just moves to the next project.
BACKOFF_AFTER_FAILURES = 5
BACKOFF = timedelta(minutes=15)


def account_snapshot(me: dict) -> dict:
    """The parts of /users/self that decide what the account may bid on."""
    status = me.get("status") or {}
    balances = me.get("account_balances") or {}
    return {
        "id": me["id"],
        "username": me.get("username"),
        "display_name": me.get("public_name") or me.get("display_name"),
        "skills": [{"id": j["id"], "name": j["name"]} for j in me.get("jobs") or []],
        "membership": (me.get("membership_package") or {}).get("name"),
        "bids_remaining": balances.get("bids_remaining"),
        "balance_usd": balances.get("equivalent_amount"),
        "preferred_freelancer": bool(me.get("preferred_freelancer")),
        "freelancer_verified": bool(status.get("freelancer_verified_user")),
        "identity_verified": bool(status.get("identity_verified")),
        "payment_verified": bool(status.get("payment_verified")),
        "limited_account": bool(me.get("limited_account")),
        "refreshed_at": utcnow().isoformat(),
    }


def account_problem(account: dict) -> str | None:
    """Why the account cannot bid on anything right now, or None."""
    if account.get("limited_account"):
        return "Freelancer has limited this account"
    if account.get("bids_remaining") == 0:
        return "no bids left on Freelancer"
    return None


def check_eligibility(project: Project, account: dict) -> str | None:
    """Why this account cannot bid on this project, or None if it can."""
    upgrades = project.upgrades or []
    if "pf_only" in upgrades and not account.get("preferred_freelancer"):
        return "Preferred Freelancers only"
    if "kyc_required" in upgrades and not account.get("identity_verified"):
        return "identity verification required"
    return None


def is_project_requirement(error_code: str | None) -> bool:
    return any(code in (error_code or "") for code in PROJECT_REQUIREMENT_CODES)
