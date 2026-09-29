"""
Password hashing and JWT access/refresh-token handling.

Access tokens carry the RBAC matrix's own design (07_RBAC_MATRIX.md §6,
layer 1: "Token claims — permissions and godown scope are baked into a
15-minute access token; role changes revoke refresh tokens so a demotion
takes effect within one token lifetime."). A verified access token is
therefore *self-contained* for authorization — `require_permission()`
(app/core/deps.py) checks the token's own claims and never re-queries the
database per request.

Refresh tokens are opaque random strings; only their SHA-256 hash is stored
(`refresh_tokens.token_hash`), so a stolen database dump doesn't hand out
usable tokens. They're looked up before any tenant is known (you can't know
which tenant a bearer token belongs to until you've already found the row
behind it), so every refresh-token operation runs through the BYPASSRLS
platform engine, matching `refresh_tokens`' deny-all RLS policy from
alembic/versions/..._rls_policies.py.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings

settings = get_settings()

# Argon2id: the current OWASP-recommended default, and already installed
# (argon2-cffi). No legacy scheme to support — this is a from-scratch app.
_pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

JWT_ALGORITHM = "HS256"


def validate_password_strength(password: str) -> None:
    """BR-AUTH-02: "Passwords >= 8 chars with at least one letter and one
    digit". Raises `ApiError(400, PASSWORD_TOO_WEAK)` with the specific
    failure, so the UI can tell the user what's actually wrong instead of
    restating the whole rule.

    Deliberately not stricter than the documented rule: inventing extra
    requirements (symbols, mixed case) would diverge from the spec the
    frontend validates against, so the two would disagree about what is
    acceptable.
    """
    from app.core.errors import CODE_PASSWORD_TOO_WEAK, ApiError

    problems = []
    if len(password) < 8:
        problems.append("at least 8 characters")
    if not any(c.isalpha() for c in password):
        problems.append("at least one letter")
    if not any(c.isdigit() for c in password):
        problems.append("at least one digit")

    if problems:
        raise ApiError(
            400,
            CODE_PASSWORD_TOO_WEAK,
            f"Password needs {', and '.join(problems)}",
            errors=[{"field": "password", "message": f"Needs {', and '.join(problems)}"}],
        )


def hash_password(plain_password: str) -> str:
    return _pwd_context.hash(plain_password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    try:
        return _pwd_context.verify(plain_password, password_hash)
    except ValueError:
        # Malformed/empty hash (e.g. an invited-but-never-activated user) —
        # never let a hashing-library exception become an auth bypass.
        return False


@dataclass
class GodownScope:
    all_godowns: bool
    godown_ids: list[str] = field(default_factory=list)

    def to_claim(self) -> dict:
        return {"all": self.all_godowns, "godown_ids": self.godown_ids}


@dataclass
class AccessTokenClaims:
    """What `require_permission()` and friends actually read back out of a
    verified token — never re-fetched from the database per request."""

    user_id: str
    company_id: Optional[str]
    role_code: str
    is_platform_admin: bool
    permissions: list[str]
    godown_scope: GodownScope
    expires_at: datetime
    issued_at: Optional[datetime] = None
    #: BR-AUTH-07. Set only on an impersonation token: the platform admin
    #: behind it, and the `impersonation_sessions` row recording the visit.
    impersonated_by: Optional[str] = None
    impersonation_id: Optional[str] = None


def create_access_token(
    *,
    user_id: UUID,
    company_id: Optional[UUID],
    role_code: str,
    is_platform_admin: bool,
    permissions: list[str],
    godown_scope: GodownScope,
    impersonated_by: Optional[UUID] = None,
    impersonation_id: Optional[UUID] = None,
    ttl_minutes: Optional[int] = None,
) -> str:
    """`ttl_minutes` overrides the configured access-token lifetime — used
    only by impersonation, which BR-AUTH-07 caps at 30 minutes."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=ttl_minutes or settings.jwt_access_ttl_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "company_id": str(company_id) if company_id else None,
        "role": role_code,
        "is_platform_admin": is_platform_admin,
        "permissions": permissions,
        "godown_scope": godown_scope.to_claim(),
        "type": "access",
        "iat": int(now.timestamp()),
        # Millisecond precision alongside the standard second-resolution
        # `iat`: instant revocation compares the two, and a user signing
        # straight back in after a password change would otherwise land in
        # the same second as the revocation marker and be refused.
        "iat_ms": int(now.timestamp() * 1000),
        "exp": int(expires_at.timestamp()),
    }
    if impersonated_by:
        payload["impersonated_by"] = str(impersonated_by)
        payload["impersonation_id"] = str(impersonation_id) if impersonation_id else None
    return jwt.encode(payload, settings.jwt_secret, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> AccessTokenClaims:
    """Raises `jose.JWTError` on anything wrong — expired, bad signature,
    malformed. Callers (app/core/deps.py) turn that into a 401."""
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[JWT_ALGORITHM])
    if payload.get("type") != "access":
        raise JWTError("not an access token")
    scope = payload.get("godown_scope") or {"all": False, "godown_ids": []}
    return AccessTokenClaims(
        user_id=payload["sub"],
        company_id=payload.get("company_id"),
        role_code=payload["role"],
        is_platform_admin=bool(payload.get("is_platform_admin", False)),
        permissions=list(payload.get("permissions", [])),
        godown_scope=GodownScope(all_godowns=bool(scope.get("all")), godown_ids=list(scope.get("godown_ids", []))),
        expires_at=datetime.fromtimestamp(payload["exp"], tz=timezone.utc),
        issued_at=(
            datetime.fromtimestamp(payload["iat_ms"] / 1000, tz=timezone.utc)
            if payload.get("iat_ms")
            else datetime.fromtimestamp(payload["iat"], tz=timezone.utc)
            if payload.get("iat")
            else None
        ),
        impersonated_by=payload.get("impersonated_by"),
        impersonation_id=payload.get("impersonation_id"),
    )


def generate_reset_token() -> tuple[str, str]:
    """Returns (opaque token for the reset link, its sha256 digest to
    store). Same reasoning as refresh tokens: the link itself is never
    persisted, so a database dump cannot be used to reset anyone's
    password."""
    raw = secrets.token_urlsafe(48)
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def hash_reset_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> tuple[str, str, datetime]:
    """Returns (opaque token to hand to the client, its sha256 hex digest to
    store, expiry). The opaque value itself is never persisted."""
    raw = secrets.token_urlsafe(48)
    token_hash = hash_refresh_token(raw)
    expires_at = datetime.now(timezone.utc) + timedelta(days=settings.jwt_refresh_ttl_days)
    return raw, token_hash, expires_at


def hash_refresh_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
