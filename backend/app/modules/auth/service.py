"""
Auth business logic — login and refresh. Runs entirely on the BYPASSRLS
platform engine: at login time we don't yet know which tenant we're in (the
whole point is to find out), and refresh-token rows are deny-all under RLS
by design (see alembic/versions/..._rls_policies.py) — only this
platform-level code path is meant to touch them at all.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import get_settings
from app.core.security import (
    GodownScope,
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
    verify_password,
)


class AuthError(Exception):
    """Any login/refresh failure the router turns into a 401. Deliberately
    one exception type with one generic client-facing message — a login
    endpoint that distinguishes "no such user" from "wrong password" in its
    response hands out a user-enumeration oracle for free."""


class AccountLockedError(Exception):
    """BR-AUTH-03: the account is temporarily locked after repeated failed
    attempts. Separate from `AuthError` because the spec gives it its own
    status (`429 RATE_LIMITED`) — and unlike the generic 401, telling a
    caller their own account is locked is not an enumeration risk, since
    they already had to get the password wrong five times to see it."""

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__("Account temporarily locked")
        self.retry_after_seconds = retry_after_seconds


class CompanySuspendedError(Exception):
    """BR-AUTH-04: a user of a suspended company cannot authenticate."""


class NotAMemberError(Exception):
    """BR-AUTH-13: switching into a company this login holds no active
    membership of (or whose company is suspended). The router turns it into
    `403 NOT_A_MEMBER`. Deliberately says nothing about *why* — "that
    company exists but you're not in it" and "no such company" look the
    same from outside."""


async def _load_user_for_login(conn: AsyncConnection, identifier: str) -> Optional[dict]:
    """BR-AUTH-01: "Login accepts a username **or** an email; both resolve
    to a single user." Both columns are globally unique, so one query over
    either is unambiguous."""
    row = (
        await conn.execute(
            text(
                "SELECT u.id, u.company_id, u.email, u.username, u.password_hash, u.full_name, "
                "u.role_id, u.status, u.is_platform_admin, u.has_all_godowns, "
                "u.failed_login_count, u.locked_until, "
                "c.status AS company_status "
                "FROM users u LEFT JOIN companies c ON c.id = u.company_id "
                "WHERE (lower(u.email) = lower(:identifier) OR lower(u.username) = lower(:identifier)) "
                "AND u.deleted_at IS NULL"
            ),
            {"identifier": identifier},
        )
    ).mappings().first()
    return dict(row) if row else None


async def register_failed_login(conn: AsyncConnection, *, identifier: str) -> None:
    """BR-AUTH-03. Called from the router *after* the failed attempt's own
    transaction has rolled back, so it needs its own.

    Counting happens for a real user only. Incrementing a counter for an
    identifier that matches nobody would be pointless (there is no row to
    lock) and would leak nothing useful, so unknown identifiers simply fall
    through — the caller still gets the same generic 401 either way.
    """
    settings = get_settings()
    await conn.execute(
        text(
            "UPDATE users SET "
            "  failed_login_count = failed_login_count + 1, "
            "  locked_until = CASE "
            "    WHEN failed_login_count + 1 >= :max_attempts "
            "    THEN now() + make_interval(mins => :lock_minutes) "
            "    ELSE locked_until END "
            "WHERE (lower(email) = lower(:identifier) OR lower(username) = lower(:identifier)) "
            "  AND deleted_at IS NULL"
        ),
        {
            "identifier": identifier,
            "max_attempts": settings.login_max_failed_attempts,
            "lock_minutes": settings.login_lockout_minutes,
        },
    )


async def _godown_scope_for(
    conn: AsyncConnection, *, user_id, has_all_godowns: bool, is_platform_admin: bool
) -> GodownScope:
    if has_all_godowns or is_platform_admin:
        return GodownScope(all_godowns=True, godown_ids=[])
    godown_rows = (
        await conn.execute(
            text("SELECT godown_id FROM user_godown_access WHERE user_id = :uid"),
            {"uid": user_id},
        )
    ).all()
    return GodownScope(all_godowns=False, godown_ids=[str(r[0]) for r in godown_rows])


async def _build_token_claims(conn: AsyncConnection, user: dict) -> tuple[str, list[str], GodownScope]:
    role_row = (
        await conn.execute(text("SELECT code FROM roles WHERE id = :id"), {"id": user["role_id"]})
    ).first()
    role_code = role_row[0]

    perm_rows = (
        await conn.execute(
            text(
                "SELECT p.code FROM role_permissions rp "
                "JOIN permissions p ON p.id = rp.permission_id "
                "WHERE rp.role_id = :role_id"
            ),
            {"role_id": user["role_id"]},
        )
    ).all()
    permissions = sorted(r[0] for r in perm_rows)

    godown_scope = await _godown_scope_for(
        conn,
        user_id=user["id"],
        has_all_godowns=user["has_all_godowns"],
        is_platform_admin=user["is_platform_admin"],
    )

    return role_code, permissions, godown_scope


async def login(conn: AsyncConnection, *, email: str, password: str) -> dict:
    """Returns {access_token, refresh_token, token_type, expires_in} plus
    identity fields the router uses for the audit row.

    `email` is really "email or username" (BR-AUTH-01); the parameter keeps
    its name because that is what the request field is called.
    """
    user = await _load_user_for_login(conn, email)
    if user is None or not user["password_hash"]:
        raise AuthError("Invalid credentials")

    # BR-AUTH-03: check the lock before checking the password. Verifying
    # first would let someone keep testing passwords against a locked
    # account and learn from the timing which guesses were right.
    locked_until = user.get("locked_until")
    if locked_until is not None and locked_until > datetime.now(timezone.utc):
        raise AccountLockedError(
            retry_after_seconds=max(1, int((locked_until - datetime.now(timezone.utc)).total_seconds()))
        )

    if not verify_password(password, user["password_hash"]):
        raise AuthError("Invalid credentials")
    if user["status"] != "active":
        raise AuthError("Account is not active")

    # BR-AUTH-04: a user of a suspended company cannot authenticate.
    # Platform admins have no company and are unaffected.
    #
    # BR-AUTH-13 refines that for a multi-company login: a suspended *home*
    # company only blocks them if they have nowhere else to go. Otherwise
    # they land in their oldest active membership instead — suspending
    # company A is not meant to lock its Owner out of company B.
    active_company_id = user["company_id"]
    if user["company_id"] is not None and user.get("company_status") == "suspended":
        active_company_id = await _first_other_active_company(conn, user_id=user["id"])
        if active_company_id is None:
            raise CompanySuspendedError()

    membership = await _membership_for(conn, user=user, company_id=active_company_id)
    if membership is None:
        # Only reachable if the fallback membership vanished between the two
        # queries above; treat it like the suspension it came from.
        raise CompanySuspendedError()
    access_token, raw_refresh, role_code = await _issue_tokens(
        conn, user=user, company_id=active_company_id, membership=membership
    )
    # A successful login clears the lockout counter (BR-AUTH-03) — the
    # threshold is about consecutive failures, not lifetime ones.
    await conn.execute(
        text(
            "UPDATE users SET last_login_at = now(), last_active_at = now(), "
            "failed_login_count = 0, locked_until = NULL WHERE id = :id"
        ),
        {"id": user["id"]},
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": get_settings().jwt_access_ttl_minutes * 60,
        # Not part of the API response — the router uses these for the
        # audit row and drops them.
        "user_id": user["id"],
        "company_id": active_company_id,
        "role_code": role_code,
    }


async def refresh(conn: AsyncConnection, *, raw_refresh_token: str) -> dict:
    """Rotates the refresh token on every use (issue a new one, revoke the
    old) — standard refresh-token-rotation practice: a replayed old token
    after rotation is itself a signal the token was stolen."""
    token_hash = hash_refresh_token(raw_refresh_token)
    token_row = (
        await conn.execute(
            text(
                "SELECT id, user_id, expires_at, revoked_at, company_id FROM refresh_tokens "
                "WHERE token_hash = :hash"
            ),
            {"hash": token_hash},
        )
    ).mappings().first()

    if token_row is None or token_row["revoked_at"] is not None:
        raise AuthError("Invalid refresh token")

    if token_row["expires_at"] < datetime.now(timezone.utc):
        raise AuthError("Refresh token expired")

    user_row = (
        await conn.execute(
            text(
                "SELECT id, company_id, role_id, status, is_platform_admin, has_all_godowns "
                "FROM users WHERE id = :id"
            ),
            {"id": token_row["user_id"]},
        )
    ).mappings().first()
    if user_row is None or user_row["status"] != "active":
        raise AuthError("Account is not active")

    # BR-AUTH-13: stay in the company the token was issued for. If that
    # membership has since been removed, fail rather than quietly dropping
    # back to the home company — the screen would still be showing the
    # other company's name while writes went to this one.
    membership = await _membership_for(conn, user=dict(user_row), company_id=token_row["company_id"])
    if membership is None:
        raise AuthError("No longer a member of this company")

    # rotate: revoke the presented token, issue a fresh one
    await conn.execute(
        text("UPDATE refresh_tokens SET revoked_at = now() WHERE id = :id"),
        {"id": token_row["id"]},
    )
    access_token, raw_refresh, _role_code = await _issue_tokens(
        conn, user=dict(user_row), company_id=token_row["company_id"], membership=membership
    )

    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": get_settings().jwt_access_ttl_minutes * 60,
    }


async def revoke_refresh_token(
    conn: AsyncConnection, *, raw_refresh_token: str
) -> tuple[Optional[UUID], Optional[UUID]]:
    """Revokes the token and returns (user_id, company_id) so the caller can
    audit the logout. Returns (None, None) for an unknown token — logging
    out with a token that was never valid is not an event worth recording,
    and silently succeeding avoids handing out a "this token existed"
    oracle."""
    token_hash = hash_refresh_token(raw_refresh_token)
    row = (
        await conn.execute(
            text(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE token_hash = :hash AND revoked_at IS NULL "
                "RETURNING user_id, company_id"
            ),
            {"hash": token_hash},
        )
    ).first()
    if row is None:
        return None, None

    user_id, company_id = row[0], row[1]
    if company_id is None:
        # NULL on the token means the home company (BR-AUTH-13); the audit
        # row belongs to whichever company the session was actually in.
        company_id = (
            await conn.execute(text("SELECT company_id FROM users WHERE id = :id"), {"id": user_id})
        ).scalar_one_or_none()
    return user_id, company_id


async def get_me(conn: AsyncConnection, *, user_id: UUID, company_id=None) -> Optional[dict]:
    """Backs `GET /auth/me` — the profile fields a JWT doesn't carry (full
    name, company name, the role's display name). Runs on the BYPASSRLS
    platform engine like the rest of this module: a platform-admin caller
    has no company_id to scope a tenant session to, so this can't go
    through `get_tenant_session` the way ordinary endpoints do.

    `company_id` is the token's *active* company (BR-AUTH-13). After a
    switch, the company name, role and godown scope reported are the ones
    for that company, not the home one — the header and every permission
    check in the UI read them from here. `home_company_id` is added so the
    UI can tell the two apart."""
    row = (
        await conn.execute(
            text(
                "SELECT u.id, u.company_id, u.email, u.full_name, u.phone, u.role_id, "
                "u.status, u.is_platform_admin, u.has_all_godowns, u.last_login_at "
                "FROM users u WHERE u.id = :id AND u.deleted_at IS NULL"
            ),
            {"id": user_id},
        )
    ).mappings().first()
    if row is None:
        return None
    user = dict(row)

    membership = await _membership_for(conn, user=user, company_id=company_id)
    if membership is None:
        return None
    active_company_id = company_id if company_id is not None else user["company_id"]

    role = (
        await conn.execute(
            text("SELECT code, name FROM roles WHERE id = :id"), {"id": membership["role_id"]}
        )
    ).mappings().first()
    company_name = None
    if active_company_id is not None:
        company_name = (
            await conn.execute(text("SELECT name FROM companies WHERE id = :c"), {"c": active_company_id})
        ).scalar_one_or_none()

    if str(active_company_id) == str(user["company_id"]):
        godown_scope = await _godown_scope_for(
            conn,
            user_id=user["id"],
            has_all_godowns=user["has_all_godowns"],
            is_platform_admin=user["is_platform_admin"],
        )
    else:
        godown_scope = GodownScope(all_godowns=True, godown_ids=[])

    return {
        **user,
        "home_company_id": user["company_id"],
        "company_id": active_company_id,
        "company_name": company_name,
        "role_id": membership["role_id"],
        "role_code": role["code"],
        "role_name": role["name"],
        "has_all_godowns": membership["has_all_godowns"],
        "godown_scope": godown_scope.to_claim(),
    }


_SELF_EDITABLE = ("full_name", "phone")


async def update_me(conn: AsyncConnection, *, user_id: UUID, values: dict) -> None:
    """Backs `PATCH /auth/me`. Whitelisted columns only — the router's
    schema already restricts them, this is the second lock on the door."""
    values = {k: v for k, v in values.items() if k in _SELF_EDITABLE}
    if not values:
        return
    assignments = ", ".join(f"{k} = :{k}" for k in values)
    await conn.execute(
        text(f"UPDATE users SET {assignments}, updated_at = now() WHERE id = :id AND deleted_at IS NULL"),
        {**values, "id": user_id},
    )


# ============================================================ memberships
#
# BR-AUTH-13. A login's home company is `users.company_id` with its role on
# `users.role_id` — unchanged, and still where every tenant-side write path
# keeps it. Any *further* company is a `company_users` row with its own
# role. See the `b7e1d4a90c52` migration for why the home company is not
# duplicated into that table.
#
# Everything here runs on the platform connection, before (or across) any
# single tenant.


async def _membership_for(conn: AsyncConnection, *, user: dict, company_id) -> Optional[dict]:
    """The role and godown scope `user` holds in `company_id`, or None if
    they may not act there right now.

    Home company (or no company, for a platform admin): the `users` row,
    exactly as before this feature existed. Anything else: an active
    `company_users` row in an active company. Non-home memberships are
    all-godowns — the console only links Owners today, and there is no
    per-company godown assignment for someone whose user row lives in
    another tenant (`user_godown_access` is scoped through `users.company_id`).
    """
    if company_id is None or str(company_id) == str(user["company_id"]):
        return {"role_id": user["role_id"], "has_all_godowns": user["has_all_godowns"]}

    row = (
        await conn.execute(
            text(
                "SELECT cu.role_id FROM company_users cu "
                "JOIN companies c ON c.id = cu.company_id "
                "WHERE cu.user_id = :u AND cu.company_id = :c AND cu.status = 'active' "
                "AND c.status = 'active' AND c.deleted_at IS NULL"
            ),
            {"u": user["id"], "c": company_id},
        )
    ).first()
    if row is None:
        return None
    return {"role_id": row[0], "has_all_godowns": True}


async def _first_other_active_company(conn: AsyncConnection, *, user_id) -> Optional[UUID]:
    """Where to land a login whose home company is suspended but who is
    still an active member elsewhere — oldest membership first, so the
    choice is stable between sign-ins."""
    return (
        await conn.execute(
            text(
                "SELECT cu.company_id FROM company_users cu "
                "JOIN companies c ON c.id = cu.company_id "
                "WHERE cu.user_id = :u AND cu.status = 'active' "
                "AND c.status = 'active' AND c.deleted_at IS NULL "
                "ORDER BY cu.added_at LIMIT 1"
            ),
            {"u": user_id},
        )
    ).scalar_one_or_none()


async def _issue_tokens(conn: AsyncConnection, *, user: dict, company_id, membership: dict) -> tuple[str, str, str]:
    """Access + refresh token for `user` acting in `company_id` with
    `membership`'s role. The refresh row remembers the company (NULL for
    home), so `/auth/refresh` keeps the session where it is.
    Returns (access_token, raw_refresh_token, role_code)."""
    scoped_user = {**user, "role_id": membership["role_id"], "has_all_godowns": membership["has_all_godowns"]}
    role_code, permissions, godown_scope = await _build_token_claims(conn, scoped_user)
    active_company_id = company_id if company_id is not None else user["company_id"]
    is_home = active_company_id is None or str(active_company_id) == str(user["company_id"])

    access_token = create_access_token(
        user_id=user["id"],
        company_id=active_company_id,
        role_code=role_code,
        is_platform_admin=user["is_platform_admin"],
        permissions=permissions,
        godown_scope=godown_scope,
    )
    raw_refresh, refresh_hash, expires_at = generate_refresh_token()
    await conn.execute(
        text(
            "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, company_id) "
            "VALUES (:user_id, :token_hash, :expires_at, :company_id)"
        ),
        {
            "user_id": user["id"],
            "token_hash": refresh_hash,
            "expires_at": expires_at,
            "company_id": None if is_home else active_company_id,
        },
    )
    return access_token, raw_refresh, role_code


async def list_companies(conn: AsyncConnection, *, user_id: UUID, active_company_id) -> list[dict]:
    """Backs `GET /auth/me/companies`: the home company first, then every
    active membership, each with the role held there. A suspended company
    is still listed, flagged by `company_status`, so the switcher can show
    it greyed out rather than have it silently disappear — switching into
    one is refused by `switch_company`."""
    rows = (
        await conn.execute(
            text(
                "SELECT c.id AS company_id, c.name AS company_name, c.status AS company_status, "
                "       r.code AS role_code, r.name AS role_name, true AS is_home "
                "FROM users u JOIN companies c ON c.id = u.company_id JOIN roles r ON r.id = u.role_id "
                "WHERE u.id = :u AND u.deleted_at IS NULL "
                "UNION ALL "
                "SELECT c.id, c.name, c.status, r.code, r.name, false "
                "FROM company_users cu JOIN companies c ON c.id = cu.company_id "
                "JOIN roles r ON r.id = cu.role_id "
                "WHERE cu.user_id = :u AND cu.status = 'active' AND c.deleted_at IS NULL "
                "ORDER BY is_home DESC, company_name"
            ),
            {"u": user_id},
        )
    ).mappings().all()
    return [{**dict(r), "is_current": str(r["company_id"]) == str(active_company_id)} for r in rows]


async def switch_company(
    conn: AsyncConnection, *, user_id: UUID, company_id: UUID, raw_refresh_token: Optional[str] = None
) -> dict:
    """BR-AUTH-13: reissue the pair for another company this login belongs
    to, without asking for the password again.

    The refresh token the client presents (if any) is revoked: it is bound
    to the company being left, and a client only ever holds one pair, so
    leaving it live would just be an orphaned credential. The *access*
    token being left is not revoked ("revokes nothing from the previous
    one") — it expires on its own within 15 minutes, and the client has
    already replaced it.
    """
    user = (
        await conn.execute(
            text(
                "SELECT id, company_id, role_id, status, is_platform_admin, has_all_godowns "
                "FROM users WHERE id = :id AND deleted_at IS NULL"
            ),
            {"id": user_id},
        )
    ).mappings().first()
    if user is None or user["status"] != "active" or user["is_platform_admin"]:
        raise NotAMemberError()
    user = dict(user)

    # `_membership_for` checks company status for other memberships; the
    # home company needs the same check here, because the home path in
    # that helper deliberately doesn't (login has its own fallback for it).
    if str(company_id) == str(user["company_id"]):
        home_status = (
            await conn.execute(text("SELECT status FROM companies WHERE id = :c"), {"c": company_id})
        ).scalar_one_or_none()
        if home_status != "active":
            raise NotAMemberError()

    membership = await _membership_for(conn, user=user, company_id=company_id)
    if membership is None:
        raise NotAMemberError()

    access_token, raw_refresh, role_code = await _issue_tokens(
        conn, user=user, company_id=company_id, membership=membership
    )
    if raw_refresh_token:
        await conn.execute(
            text(
                "UPDATE refresh_tokens SET revoked_at = now() "
                "WHERE token_hash = :hash AND user_id = :u AND revoked_at IS NULL"
            ),
            {"hash": hash_refresh_token(raw_refresh_token), "u": user["id"]},
        )
    await conn.execute(text("UPDATE users SET last_active_at = now() WHERE id = :id"), {"id": user["id"]})
    return {
        "access_token": access_token,
        "refresh_token": raw_refresh,
        "token_type": "bearer",
        "expires_in": get_settings().jwt_access_ttl_minutes * 60,
        "role_code": role_code,
    }
