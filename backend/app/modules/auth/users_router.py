"""
Users and invitations — the Administration → Users screen's backend.

07_RBAC_MATRIX.md §7 flags a real gap in the prototype here: "add role and
godown-scope editing (currently impossible after invitation)". So this
module treats role and godown scope as first-class editable properties of a
user, not just something baked in at invite time.

The invitation flow:

  1. An Owner invites someone (`POST /users/invite`). A single-use token is
     generated; only its SHA-256 hash is stored, exactly like refresh
     tokens — a stolen database dump must not yield usable invite links.
     The invitation email is recorded in `outbound_messages` in the same
     transaction and sent immediately after it commits. The raw token comes
     back in the response only in development, where there may be no mail
     server and the token is what makes the flow testable.
  2. The recipient accepts (`POST /invitations/accept`), supplying the
     token and choosing a password. This endpoint is deliberately
     **unauthenticated** — the whole point is that the user has no account
     yet — so it runs on the platform engine and identifies the tenant
     from the invitation row rather than from a token the caller supplies.
  3. Accepting creates the user, applies the invited role and godown
     scope, and marks the invitation accepted. All in one transaction: a
     half-accepted invitation would leave someone unable to log in and
     unable to be re-invited.

Security notes: invitations expire (7 days, BR-AUTH-08) and are single-use,
with `410 INVITE_EXPIRED` and `409 ALREADY_ACCEPTED` distinguished for a
caller who holds a real token while an unknown token stays a flat 400.
Role assignment is bounded by BR-AUTH-09 (you cannot grant what you do not
hold, nor change your own role), the last active Owner is protected by
BR-AUTH-10 against removal, demotion and deactivation alike, and any role
or scope change revokes that user's refresh tokens (BR-AUTH-11) so a
demotion cannot be outrun by a token issued a moment earlier.
"""

import logging
import secrets
import re
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.config import get_settings
from app.core.db import get_platform_session
from app.core.deps import get_tenant_session, require_permission, revoke_sessions
from app.core.errors import (
    CODE_ALREADY_ACCEPTED,
    CODE_BUSINESS_RULE_VIOLATION,
    CODE_DUPLICATE,
    CODE_INVITE_EXPIRED,
    CODE_LAST_OWNER,
    CODE_NOT_FOUND,
    CODE_RECORD_IN_USE,
    CODE_ROLE_ESCALATION,
    CODE_VALIDATION,
    ApiError,
)
from app.core.security import (
    AccessTokenClaims,
    hash_password,
    hash_refresh_token,
    validate_password_strength,
)
from app.modules.notifications import email as email_service
from app.modules.auth.users_schemas import (
    AcceptInvitationRequest,
    InvitationCreate,
    InvitationCreatedOut,
    InvitationOut,
    PermissionOut,
    RoleCreate,
    RoleOut,
    RoleUpdate,
    RoleUsageOut,
    UserOut,
    UserUpdate,
)

router = APIRouter(tags=["users"])

INVITATION_TTL_DAYS = 7

_USER_COLUMNS = [
    "id", "email", "full_name", "phone", "role_id", "status",
    "has_all_godowns", "last_login_at", "created_at",
]


async def _user_out(session: AsyncSession, row: dict) -> dict:
    """Adds the role code and godown scope, which live in other tables but
    are what the Users screen actually shows."""
    role_code = (
        await session.execute(text("SELECT code FROM roles WHERE id = :r"), {"r": row["role_id"]})
    ).scalar_one_or_none()
    godown_ids = [
        str(r[0])
        for r in (
            await session.execute(
                text("SELECT godown_id FROM user_godown_access WHERE user_id = :u"), {"u": row["id"]}
            )
        ).all()
    ]
    return {
        **row,
        "role_code": role_code,
        "godown_scope": "all" if row["has_all_godowns"] else "specific",
        "godown_ids": godown_ids,
    }


# ------------------------------------------------------------------ users

@router.get("/users", response_model=list[UserOut])
async def list_users(
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    rows = (
        await session.execute(
            text(
                f"SELECT {', '.join(_USER_COLUMNS)} FROM users "
                "WHERE company_id = :c AND deleted_at IS NULL ORDER BY full_name"
            ),
            {"c": claims.company_id},
        )
    ).mappings().all()
    return [await _user_out(session, dict(r)) for r in rows]


@router.get("/users/{user_id}", response_model=UserOut)
async def get_user(
    user_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    row = (
        await session.execute(
            text(
                f"SELECT {', '.join(_USER_COLUMNS)} FROM users "
                "WHERE id = :id AND company_id = :c AND deleted_at IS NULL"
            ),
            {"id": user_id, "c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return await _user_out(session, dict(row))


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """Closes the gap 07_RBAC_MATRIX.md §7 calls out: role and godown-scope
    editing after invitation."""
    before_row = (
        await session.execute(
            text(
                f"SELECT {', '.join(_USER_COLUMNS)} FROM users "
                "WHERE id = :id AND company_id = :c AND deleted_at IS NULL"
            ),
            {"id": user_id, "c": claims.company_id},
        )
    ).mappings().first()
    if before_row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    before = await _user_out(session, dict(before_row))

    values = body.model_dump(exclude_unset=True)
    role_code = values.pop("role_code", None)
    godown_scope = values.pop("godown_scope", None)
    godown_ids = values.pop("godown_ids", None)
    new_status = values.get("status")

    # BR-AUTH-09: "A user cannot ... change their own role."
    if role_code is not None and str(user_id) == claims.user_id:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_ROLE_ESCALATION,
            "You cannot change your own role",
        )

    if role_code is not None:
        role_id = await _resolve_assignable_role(session, role_code, claims)
        # BR-AUTH-09: "A user cannot assign a role with permissions
        # exceeding their own." Compared by permission set, not by role
        # rank — there is no ordering between Accountant and Godown
        # Manager, only "does this grant something I don't have".
        await _assert_no_escalation(session, role_id=role_id, claims=claims)
        values["role_id"] = role_id

    if godown_scope is not None:
        values["has_all_godowns"] = godown_scope == "all"

    # BR-AUTH-10: "The last active Owner of a company cannot be removed,
    # demoted or deactivated." Removal was already guarded; demotion and
    # deactivation are the two paths that used to slip through here.
    demoting = role_code is not None and role_code != "owner"
    deactivating = new_status is not None and new_status != "active"
    if demoting or deactivating:
        await _assert_not_last_owner(
            session,
            user_id=user_id,
            company_id=claims.company_id,
            action="demoted" if demoting else "deactivated",
        )
    if deactivating:
        # Their login stops working everywhere, including any company they
        # are a linked Owner of (demotion only changes their role here).
        await _assert_not_sole_owner_elsewhere(user_id=user_id, action="deactivated")

    if values:
        assignments = ", ".join(f"{k} = :{k}" for k in values)
        values.update({"id": user_id, "c": claims.company_id})
        await session.execute(
            text(f"UPDATE users SET {assignments} WHERE id = :id AND company_id = :c"), values
        )

    if godown_scope == "specific" and godown_ids is not None:
        await _set_godown_access(session, user_id=user_id, company_id=claims.company_id, godown_ids=godown_ids)
    elif godown_scope == "all":
        await session.execute(
            text("DELETE FROM user_godown_access WHERE user_id = :u"), {"u": user_id}
        )

    after_row = (
        await session.execute(
            text(f"SELECT {', '.join(_USER_COLUMNS)} FROM users WHERE id = :id"), {"id": user_id}
        )
    ).mappings().first()
    after = await _user_out(session, dict(after_row))

    # BR-AUTH-11: "Changing a user's role or godown scope revokes their
    # refresh tokens, forcing a permission reload." Without this, a demoted
    # user keeps their old permissions for up to the refresh-token lifetime,
    # because permissions are baked into the access token at issue time.
    if role_code is not None or godown_scope is not None:
        # `revoke_sessions` also bumps `users.sessions_revoked_at`, so the
        # access token already in their browser stops being accepted on its
        # next request rather than living out its 15 minutes.
        await revoke_sessions(session, user_id=user_id)

    await audit.record(
        session,
        entity_type="user",
        action="updated",
        claims=claims,
        entity_id=user_id,
        entity_label=after["email"],
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user(
    user_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    if str(user_id) == claims.user_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot remove your own account"
        )

    row = (
        await session.execute(
            text(
                "SELECT u.id, u.email, r.code AS role_code FROM users u "
                "JOIN roles r ON r.id = u.role_id "
                "WHERE u.id = :id AND u.company_id = :c AND u.deleted_at IS NULL"
            ),
            {"id": user_id, "c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await _assert_not_last_owner(
        session, user_id=user_id, company_id=claims.company_id, action="removed"
    )
    await _assert_not_sole_owner_elsewhere(user_id=user_id, action="removed")

    await session.execute(
        text("UPDATE users SET deleted_at = now(), status = 'inactive' WHERE id = :id AND company_id = :c"),
        {"id": user_id, "c": claims.company_id},
    )
    # Log them out everywhere: a removed user holding a valid refresh token
    # could otherwise keep minting access tokens for up to 30 days.
    await revoke_sessions(session, user_id=user_id)
    await audit.record(
        session,
        entity_type="user",
        action="removed",
        claims=claims,
        entity_id=user_id,
        entity_label=row["email"],
        request=request,
    )
    await session.commit()


# ------------------------------------------------------------ invitations

@router.post("/users/invite", response_model=InvitationCreatedOut, status_code=status.HTTP_201_CREATED)
async def invite_user(
    body: InvitationCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    existing = (
        await session.execute(
            text("SELECT 1 FROM users WHERE lower(email) = lower(:e) AND deleted_at IS NULL"),
            {"e": body.email},
        )
    ).first()
    if existing:
        raise ApiError(
            status.HTTP_409_CONFLICT, CODE_DUPLICATE, "A user with this email already exists"
        )

    # BR-AUTH-09 applies to invitations too: inviting someone as an Owner
    # is just a slower way of granting a role you may not hold.
    role_id = await _resolve_assignable_role(session, body.role_code, claims)
    await _assert_no_escalation(session, role_id=role_id, claims=claims)

    raw_token = secrets.token_urlsafe(32)
    invitation_id = uuid4()
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS)

    try:
        await session.execute(
            text(
                "INSERT INTO invitations (id, company_id, email, full_name, role_id, godown_scope, "
                "godown_ids, token_hash, invited_by, expires_at, last_sent_at) "
                "VALUES (:id, :c, :email, :full_name, :role_id, :godown_scope, "
                ":godown_ids, :token_hash, :invited_by, :expires_at, now())"
            ),
            {
                "id": invitation_id,
                "c": claims.company_id,
                "email": body.email,
                "full_name": body.full_name,
                "role_id": role_id,
                "godown_scope": body.godown_scope,
                "godown_ids": body.godown_ids or None,
                "token_hash": hash_refresh_token(raw_token),
                "invited_by": claims.user_id,
                "expires_at": expires_at,
            },
        )
    except IntegrityError:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            "There is already a pending invitation for this email",
        )

    message_id = await _queue_invitation_email(
        session,
        claims=claims,
        invitation_id=invitation_id,
        email=body.email,
        full_name=body.full_name,
        token=raw_token,
    )

    await audit.record(
        session,
        entity_type="invitation",
        action="invited",
        claims=claims,
        entity_id=invitation_id,
        entity_label=body.email,
        description=f"Invited as {body.role_code}",
        request=request,
    )
    await session.commit()

    # Sent only after the commit -- see the note in notifications/email.py
    # about never holding a transaction open across an SMTP handshake.
    await _deliver_queued_email(message_id)

    return {
        "id": invitation_id,
        "email": body.email,
        "full_name": body.full_name,
        "role_code": body.role_code,
        "expires_at": expires_at,
        # The email is now the delivery mechanism. The raw token is echoed
        # back only in development, where there may be no mail server and
        # the token is what makes the flow testable; in any other
        # environment it stays out of the response so an invite link cannot
        # be harvested by anyone who can call this endpoint.
        "invitation_token": raw_token if get_settings().is_development else None,
    }


@router.get("/invitations", response_model=list[InvitationOut])
async def list_invitations(
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
    status_filter: Optional[str] = None,
) -> list[dict]:
    where = "company_id = :c"
    params = {"c": claims.company_id}
    if status_filter:
        where += " AND status = :s"
        params["s"] = status_filter

    rows = (
        await session.execute(
            text(
                "SELECT i.id, i.email, i.full_name, r.code AS role_code, i.godown_scope, "
                "i.status, i.invited_at, i.expires_at, i.resend_count "
                f"FROM invitations i JOIN roles r ON r.id = i.role_id WHERE i.{where} "
                "ORDER BY i.invited_at DESC"
            ),
            params,
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("/invitations/{invitation_id}/resend", response_model=InvitationCreatedOut)
async def resend_invitation(
    invitation_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """Issues a *new* token and invalidates the old one. Resending the same
    token would mean an old email stays live forever; rotating means the
    most recent invite is the only one that works."""
    row = (
        await session.execute(
            text(
                "SELECT i.id, i.email, i.full_name, i.status, r.code AS role_code "
                "FROM invitations i JOIN roles r ON r.id = i.role_id "
                "WHERE i.id = :id AND i.company_id = :c"
            ),
            {"id": invitation_id, "c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if row["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This invitation is {row['status']} and cannot be resent",
        )

    raw_token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITATION_TTL_DAYS)
    await session.execute(
        text(
            "UPDATE invitations SET token_hash = :h, expires_at = :e, "
            "resend_count = resend_count + 1, last_sent_at = now() WHERE id = :id"
        ),
        {"h": hash_refresh_token(raw_token), "e": expires_at, "id": invitation_id},
    )
    message_id = await _queue_invitation_email(
        session,
        claims=claims,
        invitation_id=invitation_id,
        email=row["email"],
        full_name=row["full_name"],
        token=raw_token,
    )

    await audit.record(
        session,
        entity_type="invitation",
        action="invitation_resent",
        claims=claims,
        entity_id=invitation_id,
        entity_label=row["email"],
        request=request,
    )
    await session.commit()
    await _deliver_queued_email(message_id)

    return {
        "id": invitation_id,
        "email": row["email"],
        "full_name": row["full_name"],
        "role_code": row["role_code"],
        "expires_at": expires_at,
        "invitation_token": raw_token if get_settings().is_development else None,
    }


@router.delete("/invitations/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_invitation(
    invitation_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    row = (
        await session.execute(
            text("SELECT email, status FROM invitations WHERE id = :id AND company_id = :c"),
            {"id": invitation_id, "c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    if row["status"] != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"This invitation is already {row['status']}"
        )

    await session.execute(
        text("UPDATE invitations SET status = 'revoked' WHERE id = :id"), {"id": invitation_id}
    )
    await audit.record(
        session,
        entity_type="invitation",
        action="invitation_revoked",
        claims=claims,
        entity_id=invitation_id,
        entity_label=row["email"],
        request=request,
    )
    await session.commit()


@router.post("/invitations/accept", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def accept_invitation(
    body: AcceptInvitationRequest,
    request: Request,
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Unauthenticated by design — the caller has no account yet, so there
    is no token to scope them with. Runs on the platform engine and takes
    the tenant from the invitation row itself, never from the request."""
    token_hash = hash_refresh_token(body.invitation_token)

    async with session.begin():
        invitation = (
            await session.execute(
                text(
                    "SELECT id, company_id, email, full_name, role_id, godown_scope, godown_ids, "
                    "status, expires_at FROM invitations WHERE token_hash = :h FOR UPDATE"
                ),
                {"h": token_hash},
            )
        ).mappings().first()

        # BR-AUTH-08 names two distinct outcomes: `410 INVITE_EXPIRED` and
        # `409 ALREADY_ACCEPTED`. Both are only reachable by someone holding
        # a real token, so telling them which it is leaks nothing — whereas
        # an unknown token stays a flat 400, since distinguishing that one
        # *would* confirm which guesses are real.
        if invitation is None:
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                CODE_VALIDATION,
                "This invitation link is invalid or has expired",
            )
        if invitation["status"] == "accepted":
            raise ApiError(
                status.HTTP_409_CONFLICT,
                CODE_ALREADY_ACCEPTED,
                "This invitation has already been used",
            )
        if invitation["status"] != "pending":
            raise ApiError(
                status.HTTP_400_BAD_REQUEST,
                CODE_VALIDATION,
                f"This invitation was {invitation['status']}",
            )
        if invitation["expires_at"] < datetime.now(timezone.utc):
            await session.execute(
                text("UPDATE invitations SET status = 'expired' WHERE id = :id"), {"id": invitation["id"]}
            )
            raise ApiError(
                status.HTTP_410_GONE,
                CODE_INVITE_EXPIRED,
                "This invitation expired. Ask for a new one.",
            )

        # BR-AUTH-02 -- checked here rather than in the schema so the caller
        # gets PASSWORD_TOO_WEAK with the specific failure, not a generic
        # validation error.
        validate_password_strength(body.password)

        user_id = uuid4()
        try:
            await session.execute(
                text(
                    "INSERT INTO users (id, company_id, email, full_name, role_id, password_hash, "
                    "status, is_platform_admin, has_all_godowns, password_changed_at) "
                    "VALUES (:id, :c, :email, :full_name, :role_id, :pw, 'active', false, :all_godowns, now())"
                ),
                {
                    "id": user_id,
                    "c": invitation["company_id"],
                    "email": invitation["email"],
                    "full_name": body.full_name or invitation["full_name"],
                    "role_id": invitation["role_id"],
                    "pw": hash_password(body.password),
                    "all_godowns": invitation["godown_scope"] == "all",
                },
            )
        except IntegrityError:
            raise ApiError(
                status.HTTP_409_CONFLICT, CODE_DUPLICATE, "An account with this email already exists"
            )

        if invitation["godown_scope"] == "specific" and invitation["godown_ids"]:
            for godown_id in invitation["godown_ids"]:
                await session.execute(
                    text(
                        "INSERT INTO user_godown_access (user_id, godown_id) VALUES (:u, :g) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {"u": user_id, "g": godown_id},
                )

        await session.execute(
            text(
                "UPDATE invitations SET status = 'accepted', accepted_at = now(), "
                "accepted_user_id = :u WHERE id = :id"
            ),
            {"u": user_id, "id": invitation["id"]},
        )

        await audit.record(
            session,
            entity_type="invitation",
            action="invitation_accepted",
            company_id=invitation["company_id"],
            actor_user_id=user_id,
            entity_id=invitation["id"],
            entity_label=invitation["email"],
            request=request,
        )

        row = (
            await session.execute(
                text(f"SELECT {', '.join(_USER_COLUMNS)} FROM users WHERE id = :id"), {"id": user_id}
            )
        ).mappings().first()
        return await _user_out(session, dict(row))


async def _queue_invitation_email(
    session: AsyncSession,
    *,
    claims,
    invitation_id: UUID,
    email: str,
    full_name: str,
    token: str,
) -> UUID:
    """Records the invitation email in `outbound_messages` inside the
    caller's transaction, so the invite and the record of its email commit
    together. Returns the message id for `_deliver_queued_email`."""
    company_name = (
        await session.execute(
            text("SELECT name FROM companies WHERE id = :c"), {"c": claims.company_id}
        )
    ).scalar_one_or_none() or "your company"
    inviter = (
        await session.execute(
            text("SELECT full_name FROM users WHERE id = :u"), {"u": claims.user_id}
        )
    ).scalar_one_or_none() or "An administrator"

    spec = email_service.invitation_email(
        full_name=full_name, company_name=company_name, invited_by=inviter, token=token
    )
    spec.to = email

    return await email_service.record_outbound(
        session,
        company_id=claims.company_id,
        message_type="invitation",
        to_address=email,
        subject=spec.subject,
        body_preview=spec.body,
        related_type="invitation",
        related_id=invitation_id,
        sent_by=claims.user_id,
    )


async def _deliver_queued_email(message_id: UUID) -> None:
    """Sends a previously recorded message, after the caller has committed.

    Uses its own short-lived platform session: the request's session has
    already been committed and closed by this point, and the status update
    is bookkeeping about an already-successful operation. A failure here is
    logged on the row and never raised — the invitation itself is valid
    whether or not the email got through, and reporting a 500 would tell the
    Owner their invite failed when it didn't.
    """
    from app.core.db import PlatformSessionLocal

    row_subject = ""
    try:
        # Read and write use separate sessions so the send sits between two
        # short transactions rather than inside one long one.
        async with PlatformSessionLocal() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT to_address, subject, body_preview, company_id "
                        "FROM outbound_messages WHERE id = :id"
                    ),
                    {"id": message_id},
                )
            ).mappings().first()
            # The tenant's own SMTP settings when it has configured them,
            # otherwise the environment's (console in development).
            config = await email_service.load_company_config(session, row["company_id"]) if row else None
        if row is None:
            return

        row_subject = row["subject"]
        sent, error = email_service.send(
            email_service.EmailMessageSpec(
                to=row["to_address"], subject=row["subject"], body=row["body_preview"]
            ),
            config,
        )

        async with PlatformSessionLocal() as session:
            await email_service.mark_result(session, message_id=message_id, sent=sent, error=error)
            await session.commit()
    except Exception:  # noqa: BLE001
        logging.getLogger("app.notifications").warning(
            "Could not deliver queued email %s (%s)", message_id, row_subject, exc_info=True
        )


async def _resolve_assignable_role(session: AsyncSession, role_code: str, claims) -> UUID:
    if role_code == "super_admin":
        # Platform role; a tenant handing it out would be an escalation
        # straight out of its own tenancy.
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_ROLE_ESCALATION,
            "super_admin is a platform role and cannot be assigned within a company",
        )
    role_id = (
        await session.execute(
            text("SELECT id FROM roles WHERE code = :code AND (company_id IS NULL OR company_id = :c)"),
            {"code": role_code, "c": claims.company_id},
        )
    ).scalar_one_or_none()
    if role_id is None:
        raise ApiError(status.HTTP_400_BAD_REQUEST, CODE_VALIDATION, f"Unknown role: {role_code}")
    return role_id


async def _assert_no_escalation(session: AsyncSession, *, role_id: UUID, claims) -> None:
    """BR-AUTH-09. The caller's own permissions come from their verified
    token, so this compares what the target role grants against what the
    caller actually holds — an Owner holds everything and passes, a
    Purchase Manager trying to mint an Owner does not."""
    granted = {
        r[0]
        for r in (
            await session.execute(
                text(
                    "SELECT p.code FROM role_permissions rp JOIN permissions p ON p.id = rp.permission_id "
                    "WHERE rp.role_id = :r"
                ),
                {"r": role_id},
            )
        ).all()
    }
    excess = granted - set(claims.permissions)
    if excess:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_ROLE_ESCALATION,
            f"That role grants permissions you do not hold: {', '.join(sorted(excess)[:3])}"
            + ("…" if len(excess) > 3 else ""),
        )


_ACTIVE_OWNERS_SQL = """
    SELECT count(*) FROM (
        SELECT u.id FROM users u JOIN roles r ON r.id = u.role_id
        WHERE u.company_id = :c AND r.code = 'owner'
          AND u.deleted_at IS NULL AND u.status = 'active'
        UNION
        SELECT u.id FROM company_users cu
        JOIN roles r ON r.id = cu.role_id
        JOIN users u ON u.id = cu.user_id
        WHERE cu.company_id = :c AND r.code = 'owner' AND cu.status = 'active'
          AND u.deleted_at IS NULL AND u.status = 'active'
    ) owners
"""


async def _active_owner_count(session: AsyncSession, company_id) -> int:
    """Active Owners of one company: its own Owner users plus linked Owners
    (BR-AUTH-13). A linked Owner is an Owner of this company too — only
    their login lives in another one — so they count toward BR-AUTH-10."""
    return (await session.execute(text(_ACTIVE_OWNERS_SQL), {"c": company_id})).scalar_one()


async def _assert_not_last_owner(
    session: AsyncSession, *, user_id: UUID, company_id: str, action: str
) -> None:
    """BR-AUTH-10: the last active Owner cannot be removed, demoted or
    deactivated. The UI hides the button; the server has to mean it, or a
    tenant can lock itself out of its own account with one API call.

    `user_id` may be one of the company's own users or a linked Owner; both
    are Owners here and both count toward "the last one"."""
    is_owner = (
        await session.execute(
            text(
                "SELECT 1 FROM users u JOIN roles r ON r.id = u.role_id "
                "WHERE u.id = :id AND u.company_id = :c AND r.code = 'owner' "
                "AND u.deleted_at IS NULL AND u.status = 'active' "
                "UNION ALL "
                "SELECT 1 FROM company_users cu JOIN roles r ON r.id = cu.role_id "
                "JOIN users u ON u.id = cu.user_id "
                "WHERE cu.user_id = :id AND cu.company_id = :c AND r.code = 'owner' "
                "AND cu.status = 'active' AND u.deleted_at IS NULL AND u.status = 'active'"
            ),
            {"id": user_id, "c": company_id},
        )
    ).first()
    if not is_owner:
        return

    if await _active_owner_count(session, company_id) <= 1:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_LAST_OWNER,
            f"BR-AUTH-10: the last active Owner cannot be {action} — add or promote another Owner first",
        )


async def _assert_not_sole_owner_elsewhere(*, user_id: UUID, action: str, name_companies: bool = False) -> None:
    """BR-AUTH-10 across companies. Deactivating or removing a user ends
    their login everywhere, so if they are the only Owner of a company they
    are *linked* to, that company would be left with none.

    Runs on its own read-only platform session: a tenant session cannot see
    another tenant's `company_users` rows. The company is named only for
    the platform console — a tenant is not told about other tenants."""
    from app.core.db import PlatformSessionLocal

    async with PlatformSessionLocal() as ps:
        linked = (
            await ps.execute(
                text(
                    "SELECT cu.company_id, c.name FROM company_users cu "
                    "JOIN roles r ON r.id = cu.role_id JOIN companies c ON c.id = cu.company_id "
                    "WHERE cu.user_id = :u AND cu.status = 'active' AND r.code = 'owner'"
                ),
                {"u": user_id},
            )
        ).all()
        for company_id, company_name in linked:
            if await _active_owner_count(ps, company_id) <= 1:
                where = company_name if name_companies else "another company they are linked to"
                raise ApiError(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    CODE_LAST_OWNER,
                    f"BR-AUTH-10: this person is the only active Owner of {where} and cannot be "
                    f"{action} until it has another Owner",
                )


async def _set_godown_access(
    session: AsyncSession, *, user_id: UUID, company_id: str, godown_ids: list[UUID]
) -> None:
    valid = {
        str(r[0])
        for r in (
            await session.execute(
                text("SELECT id FROM godowns WHERE company_id = :c AND deleted_at IS NULL"),
                {"c": company_id},
            )
        ).all()
    }
    unknown = [str(g) for g in godown_ids if str(g) not in valid]
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown godown(s): {', '.join(unknown)}"
        )

    await session.execute(text("DELETE FROM user_godown_access WHERE user_id = :u"), {"u": user_id})
    for godown_id in godown_ids:
        await session.execute(
            text("INSERT INTO user_godown_access (user_id, godown_id) VALUES (:u, :g)"),
            {"u": user_id, "g": godown_id},
        )


# ================================================================== roles

# Roles are read-only. `roles.code` has a CHECK constraint pinning it to the
# seven built-in codes, so there is no create/update/delete here: the schema
# cannot express a tenant-defined role, and BR-AUTH-11 says the built-in ones
# are not editable anyway. The Roles screen exists to make the permission
# matrix *visible* — which is worth having on its own, since until now it
# showed invented data.

_ROLE_SELECT = """
    SELECT r.id, r.code, r.name, r.description, r.is_system,
           COALESCE(
               (SELECT array_agg(p.code ORDER BY p.code)
                  FROM role_permissions rp
                  JOIN permissions p ON p.id = rp.permission_id
                 WHERE rp.role_id = r.id),
               ARRAY[]::text[]
           ) AS permissions,
           (SELECT COUNT(*) FROM users u
             WHERE u.role_id = r.id
               AND u.company_id = :c
               AND u.deleted_at IS NULL) AS user_count
      FROM roles r
     WHERE (r.company_id IS NULL OR r.company_id = :c)
"""


@router.get("/roles", response_model=list[RoleOut])
async def list_roles(
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    """Every role this tenant can assign, with its real permission set.

    `super_admin` is excluded: it is a platform role with no tenant-data
    permissions at all (07_RBAC_MATRIX.md), so offering it on a tenant's
    Roles screen would imply an assignment that `POST /users/invite` would
    rightly refuse.

    The `company_id IS NULL` half of the WHERE is what makes the seven system
    roles visible to every tenant; the RLS policy on `roles` allows exactly
    that shape.
    """
    rows = (
        await session.execute(
            text(_ROLE_SELECT + " AND r.code <> 'super_admin' ORDER BY r.name"),
            {"c": claims.company_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/roles/{role_id}", response_model=RoleOut)
async def get_role(
    role_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    row = (
        await session.execute(
            text(_ROLE_SELECT + " AND r.id = :id"),
            {"c": claims.company_id, "id": role_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Role not found")
    return dict(row)


@router.get("/permissions", response_model=list[PermissionOut])
async def list_permissions(
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    """The full permission catalogue.

    `permissions` is a genuinely global table — it carries no `company_id`
    and has no RLS policy, because a permission code means the same thing in
    every tenant. Behind `user.view` rather than open, because the catalogue
    describes the shape of the authorisation system.
    """
    rows = (
        await session.execute(
            text("SELECT code, module, description FROM permissions ORDER BY module, code")
        )
    ).mappings().all()
    return [dict(r) for r in rows]


# ============================================================ custom roles
#
# BR-AUTH-09 is the whole design here: "a user cannot assign a role with
# permissions exceeding their own". Defining a role is the same act one step
# removed — a Purchase Manager who could mint a role holding
# `user.manage_owners` and then assign it would have escalated in two calls
# rather than one. So both paths run through `_assert_no_escalation`-shaped
# checks, and the built-in roles stay untouchable for everyone.

_RESERVED_CODES = {"super_admin", "owner", "purchase_manager", "godown_manager", "accountant", "staff", "viewer"}


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    slug = re.sub(r"_+", "_", slug)[:40]
    if not slug or not slug[0].isalpha():
        slug = f"role_{slug}"[:40]
    return slug.rstrip("_") or "role"


async def _assert_permissions_within_caller(session: AsyncSession, *, codes: list[str], claims) -> list[str]:
    """Every code must exist, and must be one the caller already holds."""
    wanted = sorted({c.strip() for c in codes if c and c.strip()})
    if not wanted:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            "A role needs at least one permission",
            errors=[{"field": "permissions", "message": "Choose what this role may do"}],
        )

    known = {
        r[0]
        for r in (
            await session.execute(
                text("SELECT code FROM permissions WHERE code = ANY(:codes)"), {"codes": wanted}
            )
        ).all()
    }
    unknown = [c for c in wanted if c not in known]
    if unknown:
        raise ApiError(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            CODE_VALIDATION,
            f"Unknown permission: {unknown[0]}",
            errors=[{"field": "permissions", "message": f"Unknown permission: {unknown[0]}"}],
        )

    excess = [c for c in wanted if c not in set(claims.permissions)]
    if excess:
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_ROLE_ESCALATION,
            "A role cannot grant permissions you do not hold yourself: "
            + ", ".join(excess[:3])
            + ("…" if len(excess) > 3 else ""),
        )
    return wanted


async def _role_row(session: AsyncSession, *, role_id: UUID, company_id: str) -> dict:
    row = (
        await session.execute(text(_ROLE_SELECT + " AND r.id = :id"), {"c": company_id, "id": role_id})
    ).mappings().first()
    if row is None:
        raise ApiError(status.HTTP_404_NOT_FOUND, CODE_NOT_FOUND, "Role not found")
    return dict(row)


async def _set_role_permissions(session: AsyncSession, *, role_id: UUID, codes: list[str]) -> None:
    await session.execute(text("DELETE FROM role_permissions WHERE role_id = :r"), {"r": role_id})
    if codes:
        await session.execute(
            text(
                "INSERT INTO role_permissions (role_id, permission_id) "
                "SELECT :r, p.id FROM permissions p WHERE p.code = ANY(:codes)"
            ),
            {"r": role_id, "codes": codes},
        )


@router.post("/roles", response_model=RoleOut, status_code=status.HTTP_201_CREATED)
async def create_role(
    body: RoleCreate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """Define a role of this company's own."""
    code = (body.code or _slug(body.name)).lower()
    if code in _RESERVED_CODES:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_DUPLICATE,
            f"'{code}' is the code of a built-in role — choose another",
            errors=[{"field": "code", "message": "That code belongs to a built-in role"}],
        )

    codes = list(body.permissions)
    if body.clone_from_role_id:
        source = await _role_row(session, role_id=body.clone_from_role_id, company_id=claims.company_id)
        codes = codes or list(source["permissions"])
    permissions = await _assert_permissions_within_caller(session, codes=codes, claims=claims)

    role_id = uuid4()
    try:
        await session.execute(
            text(
                "INSERT INTO roles (id, company_id, code, name, description, is_system) "
                "VALUES (:id, :c, :code, :name, :description, false)"
            ),
            {
                "id": role_id,
                "c": claims.company_id,
                "code": code,
                "name": body.name.strip(),
                "description": (body.description or "").strip() or None,
            },
        )
    except IntegrityError as exc:
        if "uq_roles_code" in str(exc.orig):
            raise ApiError(
                status.HTTP_409_CONFLICT,
                CODE_DUPLICATE,
                f"A role with the code '{code}' already exists",
                errors=[{"field": "code", "message": "Already used by another role"}],
            )
        raise
    await _set_role_permissions(session, role_id=role_id, codes=permissions)

    after = await _role_row(session, role_id=role_id, company_id=claims.company_id)
    await audit.record(
        session,
        entity_type="role",
        action="created",
        claims=claims,
        entity_id=role_id,
        entity_label=after["name"],
        after=after,
        request=request,
    )
    await session.commit()
    return after


@router.patch("/roles/{role_id}", response_model=RoleOut)
async def update_role(
    role_id: UUID,
    body: RoleUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    before = await _role_row(session, role_id=role_id, company_id=claims.company_id)
    if before["is_system"]:
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_BUSINESS_RULE_VIOLATION,
            "Built-in roles cannot be edited. Copy this one and change the copy.",
        )

    values = body.model_dump(exclude_unset=True)
    if "permissions" in values and values["permissions"] is not None:
        permissions = await _assert_permissions_within_caller(
            session, codes=values["permissions"], claims=claims
        )
        # Nobody may edit a role out from under themselves: shrinking the
        # role you are standing on is how an Owner locks their own company
        # out of user management.
        if str(before["id"]) == str(await _current_role_id(session, claims)):
            raise ApiError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                CODE_BUSINESS_RULE_VIOLATION,
                "You cannot change the permissions of the role you are signed in with",
            )
        await _set_role_permissions(session, role_id=role_id, codes=permissions)

    fields = {k: v for k, v in values.items() if k in ("name", "description")}
    if fields:
        assignments = ", ".join(f"{k} = :{k}" for k in fields)
        await session.execute(
            text(f"UPDATE roles SET {assignments} WHERE id = :id AND company_id = :c"),
            {**fields, "id": role_id, "c": claims.company_id},
        )

    after = await _role_row(session, role_id=role_id, company_id=claims.company_id)
    await audit.record(
        session,
        entity_type="role",
        action="updated",
        claims=claims,
        entity_id=role_id,
        entity_label=after["name"],
        before=before,
        after=after,
        request=request,
    )
    # Everyone on this role is holding a token whose permission list was
    # baked in at sign-in (BR-AUTH-11's reasoning, applied to the role
    # itself rather than to one user's membership of it).
    holders = (
        await session.execute(
            text("SELECT id FROM users WHERE role_id = :r AND company_id = :c AND deleted_at IS NULL"),
            {"r": role_id, "c": claims.company_id},
        )
    ).scalars().all()
    for holder in holders:
        await revoke_sessions(session, user_id=holder)

    await session.commit()
    return after


@router.get("/roles/{role_id}/usage", response_model=RoleUsageOut)
async def role_usage(
    role_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("user.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """What stands behind a role — the pre-check for the delete button."""
    row = await _role_row(session, role_id=role_id, company_id=claims.company_id)
    # Every invitation row counts, not only the pending ones: the foreign
    # key from `invitations.role_id` is ON DELETE RESTRICT, so a revoked or
    # long-accepted invitation still pins the role in place. Counting only
    # "pending" here would have the screen offer a delete the database then
    # refuses with a 500.
    counts = (
        await session.execute(
            text(
                "SELECT COUNT(*) AS total, COUNT(*) FILTER (WHERE status = 'pending') AS pending "
                "FROM invitations WHERE role_id = :r AND company_id = :c"
            ),
            {"r": role_id, "c": claims.company_id},
        )
    ).mappings().one()
    invitations, pending_invitations = counts["total"], counts["pending"]

    if row["is_system"]:
        return {
            "role_id": role_id,
            "user_count": row["user_count"],
            "invitation_count": invitations,
            "in_use": True,
            "reason": "Built-in roles cannot be deleted",
        }
    if row["user_count"]:
        return {
            "role_id": role_id,
            "user_count": row["user_count"],
            "invitation_count": invitations,
            "in_use": True,
            "reason": f"{row['user_count']} user(s) still have this role",
        }
    if invitations:
        reason = (
            f"{pending_invitations} pending invitation(s) use this role"
            if pending_invitations
            else f"{invitations} past invitation(s) still reference this role"
        )
        return {
            "role_id": role_id,
            "user_count": 0,
            "invitation_count": invitations,
            "in_use": True,
            "reason": reason,
        }
    return {"role_id": role_id, "user_count": 0, "invitation_count": 0, "in_use": False, "reason": None}


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    role_id: UUID,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("user.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> None:
    before = await _role_row(session, role_id=role_id, company_id=claims.company_id)
    usage = await role_usage(role_id, claims=claims, session=session)
    if usage["in_use"]:
        raise ApiError(status.HTTP_409_CONFLICT, CODE_RECORD_IN_USE, usage["reason"] or "This role is in use")

    await session.execute(text("DELETE FROM role_permissions WHERE role_id = :r"), {"r": role_id})
    try:
        await session.execute(
            text("DELETE FROM roles WHERE id = :id AND company_id = :c AND NOT is_system"),
            {"id": role_id, "c": claims.company_id},
        )
    except IntegrityError:
        # Belt and braces behind the usage check: whatever still references
        # the role, the answer is 409, never a 500.
        raise ApiError(
            status.HTTP_409_CONFLICT,
            CODE_RECORD_IN_USE,
            "This role is still referenced by other records and cannot be deleted",
        )
    await audit.record(
        session,
        entity_type="role",
        action="deleted",
        claims=claims,
        entity_id=role_id,
        entity_label=before["name"],
        before=before,
        request=request,
    )
    await session.commit()


async def _current_role_id(session: AsyncSession, claims) -> UUID:
    """The role the caller holds *in this company*. After a switch
    (BR-AUTH-13) that is their `company_users` role here, not the
    `users.role_id` of their home company."""
    return (
        await session.execute(
            text(
                "SELECT COALESCE("
                " (SELECT role_id FROM company_users WHERE user_id = :u AND company_id = :c AND status = 'active'),"
                " (SELECT role_id FROM users WHERE id = :u AND company_id = :c))"
            ),
            {"u": claims.user_id, "c": claims.company_id},
        )
    ).scalar_one()
