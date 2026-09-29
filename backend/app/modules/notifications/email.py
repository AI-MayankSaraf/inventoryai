"""
Outbound email.

Two responsibilities, kept apart on purpose:

  * **Recording** every message in `outbound_messages` — the table the
    schema already defines, with `message_type = 'invitation'` among its
    allowed values. That row is written in the caller's transaction, so an
    invitation and the record of its email commit together.
  * **Sending**, via a provider chosen by `EMAIL_PROVIDER`. `console` (the
    development default) logs the message; `smtp` actually delivers it.

Sending happens *after* the caller's transaction commits, never inside it.
An SMTP handshake inside a database transaction holds a connection and row
locks open for however long the mail server takes to answer, and if the
transaction then rolls back you have already sent an email about something
that didn't happen. The order here is: record as `queued` → commit → send →
mark `sent` or `failed`. A crash between the last two leaves a `queued` row,
which is exactly the state a retry job should look for.

A send failure never fails the request. If the invitation is created and the
email bounces, the invitation is still valid and can be resent — turning
that into a 500 would tell the Owner the invite failed when it didn't.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings

logger = logging.getLogger("app.notifications.email")


class EmailMessageSpec:
    """What to send, independent of how it gets sent."""

    def __init__(self, *, to: str, subject: str, body: str) -> None:
        self.to = to
        self.subject = subject
        self.body = body


async def record_outbound(
    session: AsyncSession,
    *,
    company_id: UUID | str,
    message_type: str,
    to_address: str,
    subject: str,
    body_preview: str,
    related_type: Optional[str] = None,
    related_id: Optional[UUID] = None,
    sent_by: Optional[UUID | str] = None,
) -> UUID:
    """Writes the `queued` row in the caller's transaction and returns its
    id, so the caller can mark it sent/failed once it has committed."""
    message_id = uuid4()
    settings = get_settings()
    await session.execute(
        text(
            "INSERT INTO outbound_messages "
            "(id, company_id, channel, message_type, related_type, related_id, to_address, "
            " subject, body_preview, provider, status, queued_at, sent_by) "
            "VALUES (:id, :company_id, 'email', :message_type, :related_type, :related_id, "
            " :to_address, :subject, :body_preview, :provider, 'queued', now(), :sent_by)"
        ),
        {
            "id": message_id,
            "company_id": company_id,
            "message_type": message_type,
            "related_type": related_type,
            "related_id": related_id,
            "to_address": to_address,
            "subject": subject,
            # A preview, not the body: these rows are kept for years and the
            # full text adds bulk without adding much.
            "body_preview": body_preview[:500],
            "provider": settings.email_provider,
            "sent_by": sent_by,
        },
    )
    return message_id


async def mark_result(
    session: AsyncSession, *, message_id: UUID, sent: bool, error: Optional[str] = None
) -> None:
    await session.execute(
        text(
            "UPDATE outbound_messages SET status = :status, sent_at = :sent_at, "
            "error_message = :error WHERE id = :id"
        ),
        {
            "id": message_id,
            "status": "sent" if sent else "failed",
            "sent_at": datetime.now(timezone.utc) if sent else None,
            "error": error,
        },
    )


class EmailConfig:
    """Where a message goes out from. A tenant that has configured its own
    SMTP server sends through that; everyone else falls back to the
    environment, which in development is the `console` provider."""

    def __init__(
        self,
        *,
        provider: str,
        from_address: str,
        from_name: str,
        smtp_host: str = "",
        smtp_port: int = 587,
        smtp_username: str = "",
        smtp_password: str = "",
        smtp_use_tls: bool = True,
    ) -> None:
        self.provider = provider
        self.from_address = from_address
        self.from_name = from_name
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.smtp_use_tls = smtp_use_tls


def env_config() -> EmailConfig:
    settings = get_settings()
    return EmailConfig(
        provider=settings.email_provider,
        from_address=settings.email_from,
        from_name=settings.email_from_name,
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_username=settings.smtp_username,
        smtp_password=settings.smtp_password,
        smtp_use_tls=settings.smtp_use_tls,
    )


def secrets_key() -> str:
    settings = get_settings()
    return settings.secrets_key or settings.jwt_secret


async def load_company_config(session: AsyncSession, company_id) -> EmailConfig:
    """The tenant's own SMTP settings, decrypted, or the environment's when
    it has none. Reads through whatever session the caller hands over —
    callers after a commit use a platform session, which bypasses RLS; the
    company_id predicate is what scopes it either way."""
    if company_id is None:
        return env_config()
    row = (
        await session.execute(
            text(
                "SELECT provider, from_address, from_name, smtp_host, smtp_port, smtp_username, smtp_use_tls, "
                "CASE WHEN smtp_password_encrypted IS NULL THEN NULL "
                "     ELSE pgp_sym_decrypt(smtp_password_encrypted, :key) END AS smtp_password "
                "FROM company_email_settings WHERE company_id = :c"
            ),
            {"c": company_id, "key": secrets_key()},
        )
    ).mappings().first()
    if row is None or row["provider"] == "console":
        return env_config()

    fallback = env_config()
    return EmailConfig(
        provider=row["provider"],
        from_address=row["from_address"] or fallback.from_address,
        from_name=row["from_name"] or fallback.from_name,
        smtp_host=row["smtp_host"] or "",
        smtp_port=int(row["smtp_port"] or 587),
        smtp_username=row["smtp_username"] or "",
        smtp_password=row["smtp_password"] or "",
        smtp_use_tls=bool(row["smtp_use_tls"]),
    )


def send(message: EmailMessageSpec, config: Optional[EmailConfig] = None) -> tuple[bool, Optional[str]]:
    """Blocking send. Returns (sent, error). Never raises — the caller
    decides what a failure means, and for invitations it means 'the invite
    still stands, the email didn't arrive'."""
    settings = config or env_config()
    provider = settings.provider.lower()

    if provider == "console":
        logger.info(
            "EMAIL (console provider)\n  To: %s\n  Subject: %s\n%s",
            message.to,
            message.subject,
            message.body,
        )
        return True, None

    if provider == "smtp":
        if not settings.smtp_host:
            return False, "No SMTP host is configured"
        try:
            email = EmailMessage()
            email["From"] = f"{settings.from_name} <{settings.from_address}>"
            email["To"] = message.to
            email["Subject"] = message.subject
            email.set_content(message.body)

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                if settings.smtp_username:
                    smtp.login(settings.smtp_username, settings.smtp_password)
                smtp.send_message(email)
            return True, None
        except Exception as exc:  # noqa: BLE001 — every failure is just a failed send
            logger.warning("SMTP send to %s failed: %s", message.to, exc)
            return False, str(exc)[:500]

    return False, f"Unknown email provider: {settings.provider}"


def password_reset_email(*, full_name: str, company_name: str, token: str, ttl_minutes: int) -> EmailMessageSpec:
    settings = get_settings()
    link = f"{settings.app_base_url.rstrip('/')}/reset-password?token={token}"
    body = (
        f"Hello {full_name},\n\n"
        f"Someone asked to reset the password for your {company_name} account.\n\n"
        f"Set a new password here:\n{link}\n\n"
        f"The link works once and expires in {ttl_minutes} minutes.\n\n"
        f"If this wasn't you, you can ignore this email — your password has not changed."
    )
    return EmailMessageSpec(to="", subject="Reset your password", body=body)


def test_email(*, company_name: str) -> EmailMessageSpec:
    return EmailMessageSpec(
        to="",
        subject="Test email from InventoryAI",
        body=(
            f"This is a test message from {company_name}'s InventoryAI email settings.\n\n"
            "If you are reading it, invitations and password-reset links will reach their "
            "recipients the same way."
        ),
    )


def invitation_email(*, full_name: str, company_name: str, invited_by: str, token: str) -> EmailMessageSpec:
    settings = get_settings()
    link = f"{settings.app_base_url.rstrip('/')}/accept-invitation?token={token}"
    body = (
        f"Hello {full_name},\n\n"
        f"{invited_by} has invited you to join {company_name} on {settings.email_from_name}.\n\n"
        f"Set your password and get started:\n{link}\n\n"
        f"This link expires in 7 days and can only be used once.\n\n"
        f"If you weren't expecting this invitation, you can ignore this email."
    )
    return EmailMessageSpec(
        to="",  # filled in by the caller, which knows the address
        subject=f"You've been invited to {company_name}",
        body=body,
    )
