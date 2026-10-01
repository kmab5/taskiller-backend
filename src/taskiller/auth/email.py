from __future__ import annotations

import asyncio
import base64
import html
import json
import logging
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol

from taskiller.core.config import Settings

logger = logging.getLogger(__name__)


class AuthEmailSender(Protocol):
    async def send_email_verification(self, email: str, token: str) -> None: ...

    async def send_password_reset(self, email: str, token: str) -> None: ...


class SafeLogEmailSender:
    """Token-free sink for staging environments that intentionally disable delivery."""

    async def send_email_verification(self, email: str, token: str) -> None:
        del token
        logger.info("email verification requested for %s", email)

    async def send_password_reset(self, email: str, token: str) -> None:
        del token
        logger.info("password reset requested for %s", email)


class DevelopmentLogEmailSender:
    """Local-only sink that surfaces one-time tokens for manual API development."""

    async def send_email_verification(self, email: str, token: str) -> None:
        logger.warning("DEV email verification token for %s: %s", email, token)

    async def send_password_reset(self, email: str, token: str) -> None:
        logger.warning("DEV password reset token for %s: %s", email, token)


class SMTPEmailSender:
    """Provider-agnostic SMTP delivery retained as an optional production transport."""

    def __init__(self, settings: Settings) -> None:
        if not settings.smtp_host or not settings.smtp_from_email:
            raise ValueError("SMTP host and from email are required")
        self._host = settings.smtp_host
        self._port = settings.smtp_port
        self._username = settings.smtp_username
        self._password = settings.smtp_password
        self._from_email = settings.smtp_from_email
        self._starttls = settings.smtp_starttls
        self._timeout = settings.smtp_timeout_seconds

    async def send_email_verification(self, email: str, token: str) -> None:
        await self._send(
            recipient=email,
            subject="Verify your Taskiller email",
            body=(
                "Use this one-time token to verify your Taskiller email address:\n\n"
                f"{token}\n\n"
                "Submit it to the Taskiller email-verification confirmation endpoint."
            ),
        )

    async def send_password_reset(self, email: str, token: str) -> None:
        await self._send(
            recipient=email,
            subject="Reset your Taskiller password",
            body=(
                "Use this one-time token to reset your Taskiller password:\n\n"
                f"{token}\n\n"
                "If you did not request a password reset, you can ignore this message."
            ),
        )

    async def _send(self, *, recipient: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self._from_email
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        await asyncio.to_thread(self._send_sync, message)

    def _send_sync(self, message: EmailMessage) -> None:
        with smtplib.SMTP(self._host, self._port, timeout=self._timeout) as client:
            client.ehlo()
            if self._starttls:
                client.starttls()
                client.ehlo()
            if self._username and self._password:
                client.login(self._username, self._password)
            client.send_message(message)


class MailjetEmailSender:
    """Transactional authentication email through Mailjet Send API v3.1 over HTTPS."""

    def __init__(self, settings: Settings) -> None:
        if (
            not settings.mailjet_api_key
            or not settings.mailjet_secret_key
            or not settings.mailjet_from_email
        ):
            raise ValueError("Mailjet API key, secret key, and from email are required")
        self._api_key = settings.mailjet_api_key
        self._secret_key = settings.mailjet_secret_key
        self._from_email = settings.mailjet_from_email
        self._from_name = settings.mailjet_from_name
        self._send_url = settings.mailjet_api_url
        self._timeout = settings.mailjet_timeout_seconds
        self._web_app_url = settings.web_app_url.rstrip("/")

    async def send_email_verification(self, email: str, token: str) -> None:
        link = self._auth_link("/verify-email", token)
        safe_link = html.escape(link, quote=True)
        await self._send(
            recipient=email,
            subject="Verify your Taskiller email",
            text=(
                "Verify your Taskiller email address:\n\n"
                f"{link}\n\n"
                "If you did not create this Taskiller account, you can ignore this email."
            ),
            html_body=(
                "<h1>Verify your Taskiller email</h1>"
                "<p>Confirm this address to finish setting up your account.</p>"
                f'<p><a href="{safe_link}">Verify email</a></p>'
                "<p>If you did not create this Taskiller account, you can ignore this email.</p>"
            ),
        )

    async def send_password_reset(self, email: str, token: str) -> None:
        link = self._auth_link("/reset-password", token)
        safe_link = html.escape(link, quote=True)
        await self._send(
            recipient=email,
            subject="Reset your Taskiller password",
            text=(
                "Reset your Taskiller password:\n\n"
                f"{link}\n\n"
                "If you did not request a password reset, you can ignore this email."
            ),
            html_body=(
                "<h1>Reset your Taskiller password</h1>"
                "<p>Use the link below to choose a new password.</p>"
                f'<p><a href="{safe_link}">Reset password</a></p>'
                "<p>If you did not request a password reset, you can ignore this email.</p>"
            ),
        )

    def _auth_link(self, path: str, token: str) -> str:
        query = urllib.parse.urlencode({"token": token})
        return f"{self._web_app_url}{path}?{query}"

    async def _send(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
        html_body: str,
    ) -> None:
        await asyncio.to_thread(
            self._send_sync,
            recipient=recipient,
            subject=subject,
            text=text,
            html_body=html_body,
        )

    def _send_sync(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
        html_body: str,
    ) -> None:
        payload = json.dumps(
            {
                "Messages": [
                    {
                        "From": {
                            "Email": self._from_email,
                            "Name": self._from_name,
                        },
                        "To": [{"Email": recipient}],
                        "Subject": subject,
                        "TextPart": text,
                        "HTMLPart": html_body,
                    }
                ]
            }
        ).encode("utf-8")
        credentials = base64.b64encode(f"{self._api_key}:{self._secret_key}".encode()).decode(
            "ascii"
        )
        request = urllib.request.Request(
            self._send_url,
            data=payload,
            headers={
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
                "User-Agent": "Taskiller/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                raw = response.read()
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"Mailjet Send API returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Mailjet Send API returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError("Mailjet Send API request failed") from exc

        if not raw:
            return
        try:
            body = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Mailjet Send API returned invalid JSON") from exc

        messages = body.get("Messages")
        if not isinstance(messages, list) or not messages:
            raise RuntimeError("Mailjet Send API returned no message status")
        status = str(messages[0].get("Status", "")).casefold()
        if status and status != "success":
            raise RuntimeError("Mailjet Send API did not accept the email")


@dataclass(slots=True)
class MemoryEmailSender:
    verification_tokens: dict[str, str] = field(default_factory=dict)
    reset_tokens: dict[str, str] = field(default_factory=dict)

    async def send_email_verification(self, email: str, token: str) -> None:
        self.verification_tokens[email] = token

    async def send_password_reset(self, email: str, token: str) -> None:
        self.reset_tokens[email] = token
