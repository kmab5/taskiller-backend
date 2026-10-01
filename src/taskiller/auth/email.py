from __future__ import annotations

import asyncio
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
    """Provider-agnostic SMTP delivery for production authentication email."""

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


class ResendEmailSender:
    """Transactional authentication email through the Resend HTTPS API."""

    def __init__(self, settings: Settings) -> None:
        if not settings.resend_api_key or not settings.resend_from_email:
            raise ValueError("Resend API key and from email are required")
        self._api_key = settings.resend_api_key
        self._from_email = settings.resend_from_email
        self._api_url = settings.resend_api_url.rstrip("/")
        self._timeout = settings.resend_timeout_seconds
        self._web_app_url = settings.web_app_url.rstrip("/")

    async def send_email_verification(self, email: str, token: str) -> None:
        link = self._auth_link("/verify-email", token)
        text = (
            "Verify your Taskiller email address:\n\n"
            f"{link}\n\n"
            "If you did not create this Taskiller account, you can ignore this email."
        )
        html = (
            "<h1>Verify your Taskiller email</h1>"
            "<p>Confirm this address to finish setting up your account.</p>"
            f'<p><a href="{link}">Verify email</a></p>'
            "<p>If you did not create this Taskiller account, you can ignore this email.</p>"
        )
        await self._send(
            recipient=email,
            subject="Verify your Taskiller email",
            text=text,
            html=html,
        )

    async def send_password_reset(self, email: str, token: str) -> None:
        link = self._auth_link("/reset-password", token)
        text = (
            "Reset your Taskiller password:\n\n"
            f"{link}\n\n"
            "If you did not request a password reset, you can ignore this email."
        )
        html = (
            "<h1>Reset your Taskiller password</h1>"
            "<p>Use the link below to choose a new password.</p>"
            f'<p><a href="{link}">Reset password</a></p>'
            "<p>If you did not request a password reset, you can ignore this email.</p>"
        )
        await self._send(
            recipient=email,
            subject="Reset your Taskiller password",
            text=text,
            html=html,
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
        html: str,
    ) -> None:
        await asyncio.to_thread(
            self._send_sync,
            recipient=recipient,
            subject=subject,
            text=text,
            html=html,
        )

    def _send_sync(
        self,
        *,
        recipient: str,
        subject: str,
        text: str,
        html: str,
    ) -> None:
        payload = json.dumps(
            {
                "from": self._from_email,
                "to": [recipient],
                "subject": subject,
                "text": text,
                "html": html,
            }
        ).encode()
        request = urllib.request.Request(
            f"{self._api_url}/emails",
            data=payload,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "Taskiller/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                response.read()
                if not 200 <= response.status < 300:
                    raise RuntimeError(f"Resend email API returned HTTP {response.status}")
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"Resend email API returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError("Resend email API request failed") from exc


@dataclass(slots=True)
class MemoryEmailSender:
    verification_tokens: dict[str, str] = field(default_factory=dict)
    reset_tokens: dict[str, str] = field(default_factory=dict)

    async def send_email_verification(self, email: str, token: str) -> None:
        self.verification_tokens[email] = token

    async def send_password_reset(self, email: str, token: str) -> None:
        self.reset_tokens[email] = token
