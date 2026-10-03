"""
Passwords and keys from AWS Secrets Manager (Floci locally, AWS in production).

Why: until October 2026 every database password, the JWT signing key and the
SMTP-password encryption key sat in `backend/.env` in plain text, and a blank
`JWT_SECRET` silently fell back to a key printed in the source code (security
audit H5). Now `.env` holds only *where* the secrets are; the secrets
themselves live in one Secrets Manager secret, as a JSON object:

    {
      "DATABASE_URL": "postgresql+asyncpg://postgres:...@localhost:5432/inventoryai",
      "APP_DATABASE_URL": "...",
      "PLATFORM_DATABASE_URL": "...",
      "JWT_SECRET": "...",
      "SECRETS_KEY": "...",
      "SMTP_PASSWORD": "",
      "AI_API_KEY": ""
    }

Keys are the same names `.env` uses, so moving a value is a cut-and-paste
and `scripts/secrets_manager.py` can do it for you.

How it is wired: `get_settings()` (app/core/config.py) builds the settings
once from the environment, and if `SECRETS_MANAGER_SECRET_ID` is set it
fetches this secret and lets its values win over anything in `.env`
(real environment variables still win over the secret, so a test runner can
point DATABASE_URL at a test database). A
secret that is configured but cannot be read stops the process — the same
fail-closed rule as S3 (BR-DOC-03): an API that quietly starts on the
fallback development key is exactly the H5 finding.

Credentials for Secrets Manager itself come from the normal AWS chain. On
Floci that is the dummy `test` / `test` pair already in `.env` (Floci does
not check them — they are not secrets). On AWS leave both blank and give the
server an IAM role with `secretsmanager:GetSecretValue` on this one secret.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from app.core.config import Settings

#: Everything that counts as a secret. Only these are moved out of `.env`
#: by `scripts/secrets_manager.py`, and `verify` warns if any of them is
#: still sitting there.
SECRET_ENV_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "APP_DATABASE_URL",
    "PLATFORM_DATABASE_URL",
    "JWT_SECRET",
    "SECRETS_KEY",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "AI_API_KEY",
)

#: Must be present (and non-empty) in the secret for the API to start.
REQUIRED_SECRET_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "APP_DATABASE_URL",
    "PLATFORM_DATABASE_URL",
    "JWT_SECRET",
    "SECRETS_KEY",
)


class SecretsUnavailableError(RuntimeError):
    """The configured secret could not be read. Never carries a value."""


def client(settings: "Settings"):
    import boto3
    from botocore.config import Config

    endpoint = settings.secrets_manager_endpoint_url or settings.aws_endpoint_url or None
    return boto3.client(
        "secretsmanager",
        region_name=settings.aws_region,
        endpoint_url=endpoint,
        aws_access_key_id=settings.aws_access_key_id or None,
        aws_secret_access_key=settings.aws_secret_access_key or None,
        config=Config(
            retries={"max_attempts": 3, "mode": "standard"},
            connect_timeout=5,
            read_timeout=10,
        ),
    )


def fetch_raw(settings: "Settings") -> dict[str, Any]:
    """The secret as a dict with its original (upper-case) keys."""
    secret_id = settings.secrets_manager_secret_id
    try:
        response = client(settings).get_secret_value(SecretId=secret_id)
    except Exception as exc:  # noqa: BLE001 - re-raised with a useful message, no values
        code = getattr(exc, "response", {}).get("Error", {}).get("Code", type(exc).__name__)
        raise SecretsUnavailableError(
            f"Could not read secret '{secret_id}' from Secrets Manager "
            f"({settings.secrets_manager_endpoint_url or settings.aws_endpoint_url or 'AWS'}): {code}. "
            "Is Floci running? Run `python -m scripts.secrets_manager verify` for details."
        ) from None

    raw = response.get("SecretString")
    if not raw:
        raise SecretsUnavailableError(f"Secret '{secret_id}' has no SecretString (binary secrets are not supported).")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        raise SecretsUnavailableError(f"Secret '{secret_id}' is not a JSON object.") from None
    if not isinstance(data, dict):
        raise SecretsUnavailableError(f"Secret '{secret_id}' is not a JSON object.")
    return data


def load_overrides(settings: "Settings") -> dict[str, Any]:
    """Settings field values from the secret, ready to pass as `Settings(**...)`.

    Unknown keys are ignored rather than fatal (a key added for a later
    feature must not stop today's build), and empty strings are kept: an
    empty `SMTP_PASSWORD` in the secret is a deliberate "no password".
    """
    data = fetch_raw(settings)
    missing = [k for k in REQUIRED_SECRET_KEYS if not str(data.get(k, "")).strip()]
    if missing:
        raise SecretsUnavailableError(
            f"Secret '{settings.secrets_manager_secret_id}' is missing: {', '.join(missing)}. "
            "Run `python -m scripts.secrets_manager push` to fill it in."
        )
    fields = type(settings).model_fields
    return {key.lower(): value for key, value in data.items() if key.lower() in fields}
