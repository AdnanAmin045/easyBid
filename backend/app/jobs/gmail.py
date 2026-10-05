"""Sending from the user's own Gmail through the Gmail API, authorised with OAuth.

The refresh token is the only secret kept; it is stored encrypted with a key derived from SECRET_KEY.
"""

import base64
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib.parse import urlencode

import httpx
import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.models import utcnow

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
API = "https://gmail.googleapis.com/gmail/v1/users/me"
# send: to send applications. readonly: to see replies and bounces in the threads it started.
SCOPES = ["https://www.googleapis.com/auth/gmail.send", "https://www.googleapis.com/auth/gmail.readonly"]
STATE_TTL = timedelta(minutes=10)


class GmailError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes


def _fernet(secret_key: str) -> Fernet:
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(f"gmail-token:{secret_key}".encode()).digest()))


def encrypt(value: str, secret_key: str) -> str:
    return _fernet(secret_key).encrypt(value.encode()).decode()


def decrypt(value: str, secret_key: str) -> str:
    try:
        return _fernet(secret_key).decrypt(value.encode()).decode()
    except InvalidToken:
        raise GmailError("The saved Gmail connection cannot be read (SECRET_KEY changed?). Connect Gmail again.") from None


def make_state(secret_key: str) -> str:
    """Signed, short-lived value that ties Google's callback to a request started from the dashboard."""
    return jwt.encode({"purpose": "gmail", "exp": utcnow() + STATE_TTL}, secret_key, algorithm="HS256")


def check_state(state: str, secret_key: str) -> bool:
    try:
        return jwt.decode(state, secret_key, algorithms=["HS256"]).get("purpose") == "gmail"
    except jwt.PyJWTError:
        return False


def build_message(
    *,
    sender_email: str,
    sender_name: str,
    to: str,
    cc: list[str],
    subject: str,
    body: str,
    attachment: Attachment | None = None,
) -> EmailMessage:
    """A plain-text email: no HTML, no tracking, the way a person writes one."""
    message = EmailMessage()
    message["From"] = formataddr((sender_name, sender_email)) if sender_name else sender_email
    message["To"] = to
    if cc:
        message["Cc"] = ", ".join(cc)
    message["Subject"] = subject
    message["Message-ID"] = make_msgid(domain=sender_email.rsplit("@", 1)[-1])
    message.set_content(body)
    if attachment:
        maintype, _, subtype = attachment.content_type.partition("/")
        message.add_attachment(
            attachment.data, maintype=maintype or "application", subtype=subtype or "octet-stream", filename=attachment.filename
        )
    return message


class GmailClient:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, transport: httpx.AsyncBaseTransport | None = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self._http = httpx.AsyncClient(timeout=30, transport=transport)
        self._access: dict[str, tuple[str, float]] = {}  # refresh token -> (access token, expiry timestamp)

    @property
    def configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.redirect_uri)

    async def close(self) -> None:
        await self._http.aclose()

    def auth_url(self, state: str) -> str:
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            # offline + consent: Google returns a refresh token every time, so reconnecting always works.
            "access_type": "offline",
            "prompt": "consent",
            "include_granted_scopes": "true",
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    async def _json(self, res: httpx.Response) -> dict:
        try:
            body = res.json()
        except ValueError:
            body = {}
        if res.status_code >= 400:
            error = body.get("error")
            message = (error.get("message") if isinstance(error, dict) else body.get("error_description") or error) or res.text[:200]
            raise GmailError(f"Google error {res.status_code}: {message}", res.status_code)
        return body

    async def exchange_code(self, code: str) -> dict:
        """Returns Google's token response, including refresh_token."""
        try:
            res = await self._http.post(
                TOKEN_URL,
                data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        except httpx.HTTPError as e:
            raise GmailError(f"Could not reach Google: {e!r}") from e
        tokens = await self._json(res)
        if not tokens.get("refresh_token"):
            raise GmailError("Google did not return a refresh token. Remove the app's access in your Google account and connect again.")
        return tokens

    async def access_token(self, refresh_token: str) -> str:
        cached = self._access.get(refresh_token)
        if cached and cached[1] > utcnow().timestamp() + 60:
            return cached[0]
        try:
            res = await self._http.post(
                TOKEN_URL,
                data={
                    "refresh_token": refresh_token,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "grant_type": "refresh_token",
                },
            )
        except httpx.HTTPError as e:
            raise GmailError(f"Could not reach Google: {e!r}") from e
        if res.status_code in (400, 401):
            raise GmailError("Gmail access was revoked or has expired. Connect Gmail again.", res.status_code)
        tokens = await self._json(res)
        self._access[refresh_token] = (tokens["access_token"], utcnow().timestamp() + int(tokens.get("expires_in", 3600)))
        return tokens["access_token"]

    async def profile_email(self, access_token: str) -> str:
        res = await self._http.get(f"{API}/profile", headers={"Authorization": f"Bearer {access_token}"})
        return (await self._json(res))["emailAddress"]

    async def send(self, refresh_token: str, message: EmailMessage) -> dict:
        """Send the message. Returns {'id': ..., 'threadId': ...}."""
        token = await self.access_token(refresh_token)
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        try:
            res = await self._http.post(f"{API}/messages/send", headers={"Authorization": f"Bearer {token}"}, json={"raw": raw})
        except httpx.HTTPError as e:
            # The request may or may not have reached Gmail; never retry blindly.
            raise GmailError(f"Outcome unknown, check Gmail's Sent folder before retrying: {e!r}") from e
        return await self._json(res)

    async def revoke(self, refresh_token: str) -> None:
        try:
            await self._http.post(REVOKE_URL, data={"token": refresh_token})
        except httpx.HTTPError:
            pass  # disconnecting locally matters more than telling Google
