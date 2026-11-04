"""LinkedIn's REST API: connecting an account with OAuth, uploading a poster and publishing a post.

Personal profile: the "Share on LinkedIn" product (scope w_member_social), plus "Sign In with LinkedIn using
OpenID Connect" to learn the member's id.
Company page: the Community Management API (scope w_organization_social), which LinkedIn grants to registered
organisations, in its own developer app.
"""

import asyncio
import re
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import quote, urlencode

import httpx
import jwt

from app.models import utcnow

AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
API = "https://api.linkedin.com"
SCOPES = {"personal": "openid profile w_member_social", "company": "w_organization_social"}
STATE_TTL = timedelta(minutes=10)
MAX_COMMENTARY = 3000


class LinkedInError(Exception):
    def __init__(self, message: str, status_code: int | None = None, outcome_unknown: bool = False, transient: bool = False):
        super().__init__(message)
        self.status_code = status_code
        # True when the request may have reached LinkedIn: publishing again could post twice.
        self.outcome_unknown = outcome_unknown
        self.transient = transient


@dataclass
class AppCredentials:
    client_id: str
    client_secret: str

    @property
    def ok(self) -> bool:
        return bool(self.client_id and self.client_secret)


def make_state(secret_key: str, target: str) -> str:
    """Signed, short-lived value that ties LinkedIn's callback to a request started from the dashboard."""
    return jwt.encode({"purpose": "linkedin", "target": target, "exp": utcnow() + STATE_TTL}, secret_key, algorithm="HS256")


def check_state(state: str, secret_key: str) -> str | None:
    """The target the state was made for, or None when it is not valid."""
    try:
        data = jwt.decode(state, secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return data.get("target") if data.get("purpose") == "linkedin" else None


# LinkedIn's post text format gives these characters a meaning, so a plain "(" or "#" has to be escaped.
RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")
HASHTAG = re.compile(r"#[A-Za-z][A-Za-z0-9]{1,48}")


def to_commentary(text: str, mentions: dict[str, str]) -> str:
    """Post text in LinkedIn's format: reserved characters escaped, #hashtags kept, @Name turned into a real tag.

    `mentions` maps a page name to its URN. Only names that appear in it become tags, because LinkedIn shows any other
    @name as plain text.
    """
    names = sorted(mentions, key=len, reverse=True)
    parts = [r"#[A-Za-z][A-Za-z0-9]{1,48}"]
    if names:
        parts.insert(0, "@(?:" + "|".join(re.escape(n) for n in names) + ")")
    token = re.compile("|".join(f"({p})" for p in parts))
    out: list[str] = []
    last = 0
    for found in token.finditer(text):
        out.append(RESERVED.sub(r"\\\1", text[last : found.start()]))
        piece = found.group(0)
        if piece.startswith("@"):
            name = piece[1:]
            out.append(f"@[{name}]({mentions[name]})")
        else:
            out.append(piece)
        last = found.end()
    out.append(RESERVED.sub(r"\\\1", text[last:]))
    return "".join(out)


class LinkedInClient:
    def __init__(
        self,
        personal: AppCredentials,
        company: AppCredentials,
        redirect_uri: str,
        api_version: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._apps = {"personal": personal, "company": company}
        self.redirect_uri = redirect_uri
        self.version = api_version
        self._http = httpx.AsyncClient(timeout=60, transport=transport)

    def configured(self, target: str) -> bool:
        return self._apps[target].ok

    async def close(self) -> None:
        await self._http.aclose()

    def auth_url(self, target: str, state: str) -> str:
        params = {
            "response_type": "code",
            "client_id": self._apps[target].client_id,
            "redirect_uri": self.redirect_uri,
            "state": state,
            "scope": SCOPES[target],
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    @staticmethod
    def _message(res: httpx.Response) -> str:
        try:
            body = res.json()
        except ValueError:
            return res.text[:300]
        return str(body.get("message") or body.get("error_description") or body.get("error") or body)[:300]

    def _headers(self, token: str, json: bool = True) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token}", "Linkedin-Version": self.version, "X-Restli-Protocol-Version": "2.0.0"}
        if json:
            headers["Content-Type"] = "application/json"
        return headers

    def _fail(self, res: httpx.Response, what: str) -> LinkedInError:
        message = self._message(res)
        if res.status_code == 401:
            return LinkedInError(f"LinkedIn rejected the saved login while {what}. Connect the account again. ({message})", 401)
        if res.status_code == 403:
            return LinkedInError(
                f"LinkedIn refused {what}: this account or app is not allowed to do that. For the company page, check that the "
                f"Community Management API is approved and that you are an admin of the page. ({message})",
                403,
            )
        if res.status_code == 426 or "NONEXISTENT_VERSION" in message:
            return LinkedInError(f"LinkedIn does not know API version {self.version}. Set LINKEDIN_API_VERSION to a current one. ({message})", res.status_code)
        return LinkedInError(f"LinkedIn error {res.status_code} while {what}: {message}", res.status_code, transient=res.status_code in (429, 500, 502, 503, 504))

    async def exchange_code(self, target: str, code: str) -> dict:
        app = self._apps[target]
        try:
            res = await self._http.post(
                TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": app.client_id,
                    "client_secret": app.client_secret,
                    "redirect_uri": self.redirect_uri,
                },
            )
        except httpx.HTTPError as e:
            raise LinkedInError(f"Could not reach LinkedIn: {e!r}") from e
        if res.status_code >= 400:
            raise LinkedInError(f"LinkedIn would not give a token: {self._message(res)}", res.status_code)
        return res.json()

    async def member(self, token: str) -> tuple[str, str]:
        """(urn, name) of the signed-in member, from the OpenID Connect profile."""
        try:
            res = await self._http.get(f"{API}/v2/userinfo", headers={"Authorization": f"Bearer {token}"})
        except httpx.HTTPError as e:
            raise LinkedInError(f"Could not reach LinkedIn: {e!r}") from e
        if res.status_code in (401, 403):
            raise LinkedInError(
                "LinkedIn did not share the profile. In the LinkedIn developer app, open Products and add "
                "'Sign In with LinkedIn using OpenID Connect', then connect again."
            )
        if res.status_code >= 400:
            raise self._fail(res, "reading the profile")
        body = res.json()
        return f"urn:li:person:{body['sub']}", body.get("name") or f"{body.get('given_name', '')} {body.get('family_name', '')}".strip()

    async def upload_image(self, token: str, owner: str, data: bytes) -> str:
        """Upload a poster and return its image URN."""
        try:
            res = await self._http.post(
                f"{API}/rest/images?action=initializeUpload", headers=self._headers(token), json={"initializeUploadRequest": {"owner": owner}}
            )
            if res.status_code >= 400:
                raise self._fail(res, "preparing the poster upload")
            value = res.json()["value"]
            up = await self._http.put(value["uploadUrl"], headers={"Authorization": f"Bearer {token}"}, content=data)
        except httpx.HTTPError as e:
            raise LinkedInError(f"Could not upload the poster to LinkedIn: {e!r}", transient=True) from e
        if up.status_code >= 400:
            raise self._fail(up, "uploading the poster")
        return value["image"]

    async def publish(self, token: str, author: str, text: str, mentions: dict[str, str], image: str | None = None, alt_text: str = "") -> str:
        """Create the post and return its URN. Never retried by the caller when `outcome_unknown` is set."""
        commentary = to_commentary(text, mentions)
        if len(commentary) > MAX_COMMENTARY:
            raise LinkedInError(f"The post is {len(commentary)} characters; LinkedIn allows {MAX_COMMENTARY}")
        body: dict = {
            "author": author,
            "commentary": commentary,
            "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [], "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED",
            "isReshareDisabledByAuthor": False,
        }
        if image:
            body["content"] = {"media": {"id": image, **({"altText": alt_text[:4000]} if alt_text else {})}}
        for attempt in range(3):
            try:
                res = await self._http.post(f"{API}/rest/posts", headers=self._headers(token), json=body)
            except httpx.HTTPError as e:
                raise LinkedInError(
                    f"Outcome unknown: check the LinkedIn feed before posting this again ({e!r})", outcome_unknown=True
                ) from e
            # A poster that was just uploaded can take a moment to be usable.
            if res.status_code in (404, 422) and image and attempt < 2:
                await asyncio.sleep(3 * (attempt + 1))
                continue
            break
        if res.status_code >= 400:
            raise self._fail(res, "publishing the post")
        return res.headers.get("x-restli-id") or res.headers.get("X-RestLi-Id") or ""

    async def comment(self, token: str, actor: str, post_urn: str, text: str) -> None:
        """A comment under the post, made as the same account."""
        try:
            res = await self._http.post(
                f"{API}/rest/socialActions/{quote(post_urn, safe='')}/comments",
                headers=self._headers(token),
                json={"actor": actor, "object": post_urn, "message": {"text": text[:1250]}},
            )
        except httpx.HTTPError as e:
            raise LinkedInError(f"Could not reach LinkedIn to add the comment: {e!r}") from e
        if res.status_code >= 400:
            raise self._fail(res, "adding the first comment")


def post_url(urn: str) -> str:
    return f"https://www.linkedin.com/feed/update/{urn}/" if urn else ""
