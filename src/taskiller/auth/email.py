from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

logger = logging.getLogger(__name__)


class AuthEmailSender(Protocol):
    async def send_email_verification(self, email: str, token: str) -> None: ...

    async def send_password_reset(self, email: str, token: str) -> None: ...


class SafeLogEmailSender:
    """Production-safe placeholder until a real mail provider is selected."""

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


@dataclass(slots=True)
class MemoryEmailSender:
    verification_tokens: dict[str, str] = field(default_factory=dict)
    reset_tokens: dict[str, str] = field(default_factory=dict)

    async def send_email_verification(self, email: str, token: str) -> None:
        self.verification_tokens[email] = token

    async def send_password_reset(self, email: str, token: str) -> None:
        self.reset_tokens[email] = token
