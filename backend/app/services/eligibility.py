"""Can this account bid on this project at all? Checked before any AI call.

Some requirements are visible up front (Preferred Freelancer only, identity verification, bids left).
Others Freelancer only reveals when a bid is refused, such as a minimum account balance for a currency.
Those are learned from the refusal and applied to every later project.
"""

import re
from datetime import timedelta

from app.models import Project, utcnow

# "To bid on this project, you must have at least $19 USD or equivalent in your account balance."
MIN_BALANCE = re.compile(r"at least \$?([\d,]+(?:\.\d+)?)\s*USD", re.I)
MIN_BALANCE_CODE = "BID_MINIMUM_REQUIREMENT_NOT_MET"

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


def check_eligibility(project: Project, account: dict, restrictions: dict) -> str | None:
    """Why this account cannot bid on this project, or None if it can."""
    upgrades = project.upgrades or []
    if "pf_only" in upgrades and not account.get("preferred_freelancer"):
        return "Preferred Freelancers only"
    if "kyc_required" in upgrades and not account.get("identity_verified"):
        return "identity verification required"

    required = (restrictions.get("currency_min_balance_usd") or {}).get(project.currency)
    balance = account.get("balance_usd")
    if required and balance is not None and balance < required:
        return f"{project.currency} projects need ${required:g} in your Freelancer balance (you have ${balance:.2f})"
    return None


def learn_from_refusal(restrictions: dict, project: Project, error_code: str | None, message: str) -> str | None:
    """Record a requirement Freelancer revealed by refusing a bid. Returns a description if something was learned."""
    if error_code and MIN_BALANCE_CODE in error_code:
        found = MIN_BALANCE.search(message)
        if found:
            required = float(found.group(1).replace(",", ""))
            by_currency = dict(restrictions.get("currency_min_balance_usd") or {})
            by_currency[project.currency] = required
            restrictions["currency_min_balance_usd"] = by_currency
            return f"{project.currency} projects need ${required:g} in your Freelancer balance"
    return None
