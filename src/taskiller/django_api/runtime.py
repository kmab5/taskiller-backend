from __future__ import annotations

from functools import lru_cache

from taskiller.auth.email import (
    AuthEmailSender,
    DevelopmentLogEmailSender,
    MailjetEmailSender,
    SafeLogEmailSender,
    SMTPEmailSender,
)
from taskiller.core.config import EmailDeliveryMode, Settings, get_settings


@lru_cache(maxsize=1)
def taskiller_settings() -> Settings:
    return get_settings()


@lru_cache(maxsize=1)
def auth_email_sender() -> AuthEmailSender:
    settings = taskiller_settings()
    if settings.email_delivery_mode is EmailDeliveryMode.SMTP:
        return SMTPEmailSender(settings)
    if settings.email_delivery_mode is EmailDeliveryMode.MAILJET:
        return MailjetEmailSender(settings)
    if settings.email_delivery_mode is EmailDeliveryMode.SAFE_LOG:
        return SafeLogEmailSender()
    return DevelopmentLogEmailSender()
