import asyncio
from datetime import datetime, timezone

import httpx

RETRY_STATUSES = {429, 500, 502, 503, 504}


class FreelancerError(Exception):
    def __init__(self, message: str, status_code: int | None = None, error_code: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code

    def __str__(self) -> str:
        parts = [p for p in (self.error_code, super().__str__()) if p]
        return " - ".join(parts)


class FreelancerClient:
    def __init__(self, token: str, base_url: str, transport: httpx.AsyncBaseTransport | None = None):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"freelancer-oauth-v1": token},
            timeout=30,
            transport=transport,
        )

    async def close(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, retries: int = 0, **kwargs) -> dict:
        attempt = 0
        while True:
            try:
                res = await self._http.request(method, path, **kwargs)
            except httpx.HTTPError as e:
                if attempt < retries:
                    attempt += 1
                    await asyncio.sleep(2**attempt)
                    continue
                raise FreelancerError(f"Request failed: {e!r}") from e

            if res.status_code in RETRY_STATUSES and attempt < retries:
                attempt += 1
                await asyncio.sleep(2**attempt)
                continue

            try:
                body = res.json()
            except ValueError:
                raise FreelancerError(f"Non-JSON response: {res.text[:200]}", res.status_code) from None

            if res.status_code >= 400 or body.get("status") != "success":
                raise FreelancerError(
                    body.get("message") or f"HTTP {res.status_code}", res.status_code, body.get("error_code")
                )
            return body.get("result") or {}

    async def _get(self, path: str, params: dict | None = None) -> dict:
        return await self._request("GET", path, params=params, retries=2)

    async def get_self(self) -> dict:
        """The account that owns the token: profile skills, verification, bids left and balance."""
        params = ("jobs", "status", "membership_details", "balance_details", "preferred_details", "limited_account")
        return await self._get("/users/0.1/self/", {name: "true" for name in params})

    async def list_skills(self) -> list[dict]:
        result = await self._get("/projects/0.1/jobs/")
        return [{"id": j["id"], "name": j["name"]} for j in result]

    async def search_active_projects(self, skill_ids: list[int], limit: int = 50) -> list[dict]:
        params = {
            "jobs[]": skill_ids,
            "limit": limit,
            "full_description": "true",
            "job_details": "true",
            "sort_field": "time_updated",
        }
        result = await self._get("/projects/0.1/projects/active/", params)
        return result.get("projects") or []

    async def get_bids(self, bid_ids: list[int]) -> list[dict]:
        result = await self._get("/projects/0.1/bids/", {"bids[]": bid_ids, "limit": len(bid_ids)})
        return result.get("bids") or []

    async def place_bid(
        self, *, project_id: int, bidder_id: int, amount: float, period: int, milestone_percentage: int, description: str
    ) -> dict:
        # Never retried: a bid that timed out may still have been placed.
        return await self._request(
            "POST",
            "/projects/0.1/bids/",
            json={
                "project_id": project_id,
                "bidder_id": bidder_id,
                "amount": amount,
                "period": period,
                "milestone_percentage": milestone_percentage,
                "description": description,
            },
        )


def normalize_project(raw: dict) -> dict:
    """Map a Freelancer project payload onto Project columns."""
    budget = raw.get("budget") or {}
    stats = raw.get("bid_stats") or {}
    jobs = raw.get("jobs") or []
    commitment = (raw.get("hourly_project_info") or {}).get("commitment") or {}
    submitted = raw.get("time_submitted") or raw.get("submitdate")
    return {
        "id": raw["id"],
        "title": (raw.get("title") or "")[:500],
        "description": raw.get("description") or raw.get("preview_description") or "",
        "url": f"https://www.freelancer.com/projects/{raw['seo_url']}" if raw.get("seo_url") else "",
        "type": raw.get("type") or "fixed",
        "currency": (raw.get("currency") or {}).get("code") or "USD",
        "usd_rate": (raw.get("currency") or {}).get("exchange_rate") or 1.0,
        "budget_min": budget.get("minimum"),
        "budget_max": budget.get("maximum"),
        "weekly_hours": commitment.get("hours"),
        "bid_count": stats.get("bid_count") or 0,
        "bid_avg": stats.get("bid_avg"),
        "skills": [j["name"] for j in jobs],
        "skill_ids": [j["id"] for j in jobs],
        "language": raw.get("language"),
        "upgrades": sorted(
            [k for k, v in (raw.get("upgrades") or {}).items() if v is True]
            + (["kyc_required"] if raw.get("is_seller_kyc_required") else [])
        ),
        "submitted_at": datetime.fromtimestamp(submitted, timezone.utc) if submitted else None,
    }


def bid_status(raw: dict) -> str:
    if raw.get("retracted"):
        return "retracted"
    return raw.get("award_status") or raw.get("frontend_bid_status") or "active"
