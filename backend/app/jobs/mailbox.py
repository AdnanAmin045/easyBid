"""One way to send and to look for answers, whether the account is a Gmail (API) or any other mailbox (SMTP and IMAP).

The rest of the app asks an account for a `Mailbox` and never needs to know which kind it is.

SMTP has no threads. The Message-ID of the first email stands in for the thread id: follow-ups reply to it, and
answers are found through the headers (References, In-Reply-To) or by sender, in the IMAP inbox.
"""

import asyncio
import imaplib
import smtplib
import socket
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email import message_from_bytes
from email.message import EmailMessage

from app.config import get_env
from app.jobs import gmail as gmail_lib
from app.jobs.gmail import GmailError
from app.jobs.models import GmailAccount

TIMEOUT = 30
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
HEADERS = "FROM AUTO-SUBMITTED"


class Mailbox:
    async def send(self, message: EmailMessage, thread_id: str | None = None) -> dict:
        """Send. Returns {'id': ..., 'threadId': ...}."""
        raise NotImplementedError

    async def thread(self, thread_id: str) -> list[dict]:
        """The other messages of a conversation, with their From and Auto-Submitted headers, as Gmail returns them."""
        raise NotImplementedError

    async def answered_by(self, address: str, since: datetime) -> bool:
        """Whether `address` wrote to this mailbox after `since`, in any conversation (automatic mail does not count)."""
        raise NotImplementedError


class GmailMailbox(Mailbox):
    def __init__(self, client: gmail_lib.GmailClient, refresh_token: str):
        self.client, self.refresh = client, refresh_token

    async def send(self, message, thread_id=None):
        return await self.client.send(self.refresh, message, thread_id=thread_id)

    async def thread(self, thread_id):
        return await self.client.thread(self.refresh, thread_id)

    async def answered_by(self, address, since):
        return await self.client.answered_by(self.refresh, address, since)


@dataclass
class SmtpSettings:
    host: str
    port: int
    secure: bool  # True: TLS from the start (port 465). False: STARTTLS (port 587)
    user: str
    password: str
    imap_host: str
    imap_port: int


def connect(host: str, port: int, timeout: float) -> socket.socket:
    """Open a connection, trying IPv4 addresses before IPv6, and say what happened with each address if all fail.

    Many hosts (Render, for one) have no IPv6 route, and Python only reports the last address it tried: a plain
    "Network is unreachable" then hides that the IPv4 address timed out or was refused.
    """
    errors = []
    for family, kind, proto, _, address in sorted(socket.getaddrinfo(host, port, type=socket.SOCK_STREAM), key=lambda i: i[0] != socket.AF_INET):
        sock = socket.socket(family, kind, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(address)
            return sock
        except OSError as e:
            sock.close()
            errors.append(f"{'IPv4' if family == socket.AF_INET else 'IPv6'} {address[0]}: {e.strerror or e!r}")
    raise OSError("; ".join(errors) or "no address found")


class _Smtp(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        return connect(host, port, timeout)


class _SmtpSsl(smtplib.SMTP_SSL):
    def _get_socket(self, host, port, timeout):
        return self.context.wrap_socket(connect(host, port, timeout), server_hostname=self._host)


class _ImapSsl(imaplib.IMAP4_SSL):
    def _create_socket(self, timeout):
        return self.ssl_context.wrap_socket(connect(self.host, self.port, timeout), server_hostname=self.host)


class SmtpDriver:
    """The sockets behind SMTP and IMAP. Tests replace the three classes with fakes."""

    smtp_ssl = _SmtpSsl
    smtp_plain = _Smtp
    imap_ssl = _ImapSsl

    def smtp(self, s: SmtpSettings):
        context = ssl.create_default_context()
        if s.secure:
            return self.smtp_ssl(s.host, s.port, timeout=TIMEOUT, context=context)
        conn = self.smtp_plain(s.host, s.port, timeout=TIMEOUT)
        conn.ehlo()
        conn.starttls(context=context)
        conn.ehlo()
        return conn

    def imap(self, s: SmtpSettings):
        conn = self.imap_ssl(s.imap_host, s.imap_port, timeout=TIMEOUT, ssl_context=ssl.create_default_context())
        conn.login(s.user, s.password)
        return conn


def _imap_date(when: datetime) -> str:
    when = when.astimezone(timezone.utc)
    return f"{when.day:02d}-{MONTHS[when.month - 1]}-{when.year}"


def _headers(raw: bytes) -> dict[str, str]:
    parsed = message_from_bytes(raw)
    return {k.lower(): str(v) for k, v in parsed.items()}


class SmtpMailbox(Mailbox):
    def __init__(self, driver: SmtpDriver, settings: SmtpSettings):
        self.driver, self.s = driver, settings

    # --- sending ---

    def _send(self, message: EmailMessage) -> None:
        s = self.s
        try:
            conn = self.driver.smtp(s)
        except (OSError, smtplib.SMTPException) as e:
            raise GmailError(f"Could not reach {s.host}:{s.port}: {e!r}") from e  # nothing was sent, trying later is safe
        try:
            try:
                conn.login(s.user, s.password)
            except smtplib.SMTPAuthenticationError as e:
                raise GmailError(f"{s.user}: the mailbox refused the login ({e.smtp_code}). Check the password in Email settings.", 401) from e
            except (OSError, smtplib.SMTPException) as e:
                raise GmailError(f"Could not log in to {s.host}: {e!r}") from e
            try:
                conn.send_message(message)
            except smtplib.SMTPRecipientsRefused as e:
                reasons = "; ".join(f"{r}: {code} {msg.decode(errors='replace') if isinstance(msg, bytes) else msg}" for r, (code, msg) in e.recipients.items())
                raise GmailError(f"The mail server refused the recipient. {reasons}", 400) from e
            except smtplib.SMTPResponseException as e:
                text = e.smtp_error.decode(errors="replace") if isinstance(e.smtp_error, bytes) else str(e.smtp_error)
                # 4xx is the server slowing us down (limits, greylisting); 5xx is a refusal that will not change.
                raise GmailError(f"The mail server answered {e.smtp_code}: {text}", 429 if 400 <= e.smtp_code < 500 else 400) from e
            except Exception as e:
                # The connection broke after the message may have been handed over: never send it again blindly.
                raise GmailError(f"Outcome unknown, check the Sent folder before retrying: {e!r}", outcome_unknown=True) from e
        finally:
            try:
                conn.quit()
            except Exception:
                pass

    async def send(self, message, thread_id=None):
        await asyncio.to_thread(self._send, message)
        message_id = str(message["Message-ID"])
        return {"id": message_id, "threadId": thread_id or message_id}

    # --- looking for answers ---

    def _search(self, *criteria: str, since: datetime | None = None) -> list[dict]:
        """Messages in the inbox matching IMAP search criteria: {'headers': {...}, 'date': datetime}."""
        try:
            conn = self.driver.imap(self.s)
        except (OSError, imaplib.IMAP4.error) as e:
            raise GmailError(f"Could not read the inbox of {self.s.user}: {e!r}") from e
        try:
            conn.select("INBOX", readonly=True)
            kind, data = conn.uid("SEARCH", None, *criteria)
            if kind != "OK" or not data or not data[0]:
                return []
            found = []
            for uid in data[0].split()[-50:]:
                kind, parts = conn.uid("FETCH", uid, f"(INTERNALDATE BODY.PEEK[HEADER.FIELDS ({HEADERS})])")
                if kind != "OK":
                    continue
                for part in parts:
                    if not isinstance(part, tuple):
                        continue
                    stamp = imaplib.Internaldate2tuple(part[0])
                    arrived = datetime(*stamp[:6], tzinfo=timezone.utc) if stamp else None
                    found.append({"id": f"imap-{uid.decode()}", "headers": _headers(part[1]), "date": arrived})
            return found
        except imaplib.IMAP4.error as e:
            raise GmailError(f"Could not search the inbox of {self.s.user}: {e!r}") from e
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    @staticmethod
    def _as_message(found: dict) -> dict:
        return {"id": found["id"], "payload": {"headers": [{"name": k, "value": v} for k, v in found["headers"].items()]}}

    def _thread(self, thread_id: str) -> list[dict]:
        quoted = '"' + thread_id.replace('"', "") + '"'
        replies = self._search("OR", "HEADER", "References", quoted, "HEADER", "In-Reply-To", quoted)
        # A bounce does not reply in the thread, but it quotes the original message, Message-ID included.
        bounces = self._search("TEXT", quoted, "OR", "FROM", '"mailer-daemon"', "FROM", '"postmaster"')
        return [self._as_message(m) for m in replies + bounces]

    async def thread(self, thread_id):
        return await asyncio.to_thread(self._thread, thread_id)

    def _answered_by(self, address: str, since: datetime) -> bool:
        for m in self._search("FROM", '"' + address.replace('"', "") + '"', "SINCE", _imap_date(since)):
            if m["date"] is not None and m["date"] < since:
                continue  # SINCE works in whole days: something from earlier that day is not an answer
            sender = m["headers"].get("from", "").lower()
            if "mailer-daemon" in sender or "postmaster" in sender:
                continue
            if m["headers"].get("auto-submitted", "no").strip().lower() in ("", "no"):
                return True
        return False

    async def answered_by(self, address, since):
        return await asyncio.to_thread(self._answered_by, address, since)

    # --- checking the settings before they are saved ---

    def check(self) -> None:
        """Log in to SMTP and to IMAP. Raises GmailError saying which one failed."""
        s = self.s
        try:
            conn = self.driver.smtp(s)
        except (OSError, smtplib.SMTPException) as e:
            raise GmailError(f"Could not reach the SMTP server {s.host}:{s.port}: {e!r}") from e
        try:
            conn.login(s.user, s.password)
        except smtplib.SMTPAuthenticationError as e:
            raise GmailError(f"SMTP login refused ({e.smtp_code}). Check the mailbox email and password.", 401) from e
        except (OSError, smtplib.SMTPException) as e:
            raise GmailError(f"SMTP login failed: {e!r}") from e
        finally:
            try:
                conn.quit()
            except Exception:
                pass
        try:
            self.driver.imap(s).logout()
        except imaplib.IMAP4.error as e:
            raise GmailError(f"IMAP login refused ({s.imap_host}). Replies cannot be read without it: {e}") from e
        except OSError as e:
            raise GmailError(f"Could not reach the IMAP server {s.imap_host}:{s.imap_port}: {e!r}") from e


def smtp_settings(account: GmailAccount) -> SmtpSettings:
    return SmtpSettings(
        host=account.smtp_host,
        port=account.smtp_port,
        secure=account.smtp_secure,
        user=account.smtp_user or account.email,
        password=gmail_lib.decrypt(account.smtp_password, get_env().secret_key),
        imap_host=account.imap_host,
        imap_port=account.imap_port,
    )


def open_mailbox(js, account: GmailAccount) -> Mailbox:
    """The mailbox of an account. Raises GmailError when the saved secret can no longer be read."""
    if account.kind == "smtp":
        return SmtpMailbox(js.smtp, smtp_settings(account))
    return GmailMailbox(js.gmail, gmail_lib.decrypt(account.refresh_token, get_env().secret_key))
