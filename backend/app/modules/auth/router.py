from uuid import UUID

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core import rate_limit
from app.core.db import get_platform_session
from app.core.deps import get_current_claims
from app.core.errors import (
    CODE_COMPANY_SUSPENDED,
    CODE_FORBIDDEN,
    CODE_INVALID_CREDENTIALS,
    CODE_INVALID_RESET_TOKEN,
    CODE_NOT_A_MEMBER,
    CODE_RATE_LIMITED,
    ApiError,
)
from app.core.security import AccessTokenClaims
from app.modules.auth import password_service, service
from app.modules.auth.schemas import (
    AcceptedResponse,
    ChangePasswordRequest,
    CompanyMembershipOut,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MeOut,
    RefreshRequest,
    ResetPasswordRequest,
    SwitchCompanyRequest,
    TokenResponse,
    UpdateMeRequest,
)
from app.modules.auth.service import AccountLockedError, AuthError, CompanySuspendedError, NotAMemberError

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_platform_session),
) -> TokenResponse:
    rate_limit.refuse_if_exhausted(request, "login", account=body.email)
    try:
        async with session.begin():
            result = await service.login(session, email=body.email, password=body.password)
            # Same transaction as the login's own writes (refresh token,
            # last_login_at), per 06_BUSINESS_RULES.md §15.
            await audit.record(
                session,
                entity_type="user",
                action="logged_in",
                entity_id=result["user_id"],
                entity_label=body.email,
                company_id=result["company_id"],
                actor_user_id=result["user_id"],
                actor_role=result["role_code"],
                request=request,
            )

    except AccountLockedError as exc:
        # BR-AUTH-03 -> 429 RATE_LIMITED. Nothing to count against the
        # account: it is already locked, and letting further attempts extend
        # the lock would let an attacker keep a victim locked out
        # indefinitely. The client's own failure count still goes up.
        rate_limit.record_failure(request, "login", account=body.email)
        async with session.begin():
            await audit.record(
                session,
                entity_type="user",
                action="login_failed",
                entity_label=body.email,
                description="Attempt against a locked account",
                request=request,
            )
        raise ApiError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            CODE_RATE_LIMITED,
            "Too many failed attempts. Try again later.",
            headers={"Retry-After": str(exc.retry_after_seconds)},
        )

    except CompanySuspendedError:
        async with session.begin():
            await audit.record(
                session,
                entity_type="user",
                action="login_failed",
                entity_label=body.email,
                description="Company suspended",
                request=request,
            )
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_COMPANY_SUSPENDED,
            "This company account is suspended. Contact support.",
        )

    except AuthError:
        # The failed-login transaction rolled back, so both the counter and
        # the audit row need their own — a failure we didn't record is
        # exactly the one an intrusion would rely on.
        rate_limit.record_failure(request, "login", account=body.email)
        async with session.begin():
            await service.register_failed_login(session, identifier=body.email)
            await audit.record(
                session,
                entity_type="user",
                action="login_failed",
                entity_label=body.email,
                description="Invalid credentials or inactive account",
                request=request,
            )
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            CODE_INVALID_CREDENTIALS,
            "Invalid credentials",
        )

    # Built field-by-field rather than TokenResponse(**result): `result`
    # also carries user_id/company_id/role_code for the audit row above,
    # which have no business being in an API response.
    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, session: AsyncSession = Depends(get_platform_session)) -> TokenResponse:
    try:
        async with session.begin():
            result = await service.refresh(session, raw_refresh_token=body.refresh_token)
    except AuthError:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            CODE_INVALID_CREDENTIALS,
            "Invalid or expired refresh token",
        )
    return TokenResponse(**result)


@router.get("/me", response_model=MeOut)
async def me(
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    result = await service.get_me(session, user_id=UUID(claims.user_id), company_id=claims.company_id)
    if result is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_INVALID_CREDENTIALS, "User not found")
    return result


@router.patch("/me", response_model=MeOut)
async def update_me(
    body: UpdateMeRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_platform_session),
) -> dict:
    """Edit your own name and phone. Needs no permission beyond being
    signed in — `PATCH /users/{id}` requires `user.manage`, which most
    people don't hold, and nobody should need it to fix their own name."""
    if claims.impersonated_by:
        # BR-AUTH-07: impersonation is for looking, not for editing.
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_FORBIDDEN,
            "A profile cannot be edited while impersonating this user",
        )
    user_id = UUID(claims.user_id)
    before = await service.get_me(session, user_id=user_id, company_id=claims.company_id)
    if before is None:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, CODE_INVALID_CREDENTIALS, "User not found")

    values = body.model_dump(exclude_unset=True)
    if "full_name" in values:
        values["full_name"] = (values["full_name"] or "").strip() or before["full_name"]
    if "phone" in values:
        values["phone"] = (values["phone"] or "").strip() or None
    changed = {k: v for k, v in values.items() if v != before.get(k)}

    if changed:
        await service.update_me(session, user_id=user_id, values=changed)
        await audit.record(
            session,
            entity_type="user",
            action="updated",
            claims=claims,
            entity_id=user_id,
            entity_label=before["email"],
            description="Updated own profile",
            before={k: before.get(k) for k in changed},
            after=changed,
            request=request,
        )
        await session.commit()

    result = await service.get_me(session, user_id=user_id, company_id=claims.company_id)
    return result


# ================================================ multi-company (BR-AUTH-13)

@router.get("/me/companies", response_model=list[CompanyMembershipOut])
async def my_companies(
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_platform_session),
) -> list[dict]:
    """Companies this login can switch into, home first. An impersonation
    session gets only the company it is looking at — the admin is visiting
    one tenant, not borrowing the person's whole account."""
    if claims.is_platform_admin:
        return []
    rows = await service.list_companies(
        session, user_id=UUID(claims.user_id), active_company_id=claims.company_id
    )
    if claims.impersonated_by:
        rows = [r for r in rows if r["is_current"]]
    return rows


@router.post("/switch-company", response_model=TokenResponse)
async def switch_company(
    body: SwitchCompanyRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_platform_session),
) -> TokenResponse:
    """Not permission-gated (07_RBAC_MATRIX.md: "switching companies is not
    a new permission") — membership-gated, inside the service. The role in
    the new token is the one held in the target company, not the current
    one."""
    if claims.impersonated_by:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "Switching company is not available while impersonating"
        )
    if claims.is_platform_admin:
        raise ApiError(status.HTTP_403_FORBIDDEN, CODE_FORBIDDEN, "Platform admins have no company to switch")

    try:
        async with session.begin():
            result = await service.switch_company(
                session,
                user_id=UUID(claims.user_id),
                company_id=body.company_id,
                raw_refresh_token=body.refresh_token,
            )
            # Recorded as a sign-in *to the target company*, so it shows up
            # in that company's own activity log; the description says how.
            await audit.record(
                session,
                entity_type="user",
                action="logged_in",
                entity_id=UUID(claims.user_id),
                company_id=body.company_id,
                actor_user_id=UUID(claims.user_id),
                actor_role=result["role_code"],
                description="Switched company (multi-company login)",
                request=request,
            )
    except NotAMemberError:
        raise ApiError(
            status.HTTP_403_FORBIDDEN, CODE_NOT_A_MEMBER, "You don't have access to that company"
        )

    return TokenResponse(
        access_token=result["access_token"],
        refresh_token=result["refresh_token"],
        token_type=result["token_type"],
        expires_in=result["expires_in"],
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    body: LogoutRequest,
    request: Request,
    session: AsyncSession = Depends(get_platform_session),
) -> None:
    async with session.begin():
        user_id, company_id = await service.revoke_refresh_token(
            session, raw_refresh_token=body.refresh_token
        )
        if user_id is not None:
            await audit.record(
                session,
                entity_type="user",
                action="logged_out",
                entity_id=user_id,
                company_id=company_id,
                actor_user_id=user_id,
                request=request,
            )


# ===================================================== password reset

@router.post("/forgot-password", response_model=AcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def forgot_password(
    body: ForgotPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_platform_session),
) -> AcceptedResponse:
    """Always 202, whether or not the address belongs to an account —
    anything else is an account-enumeration oracle. The mail goes out after
    the commit, like invitations."""
    # A 429 says nothing about whether the address has an account: the
    # count is per client and address, whichever it is.
    rate_limit.enforce(request, "forgot_password", account=body.email)
    async with session.begin():
        issued = await password_service.request_reset(session, email=body.email, request=request)

    if issued is not None:
        message_id, _user_id, _raw = issued
        await _deliver(message_id)
    return AcceptedResponse()


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(
    body: ResetPasswordRequest,
    request: Request,
    session: AsyncSession = Depends(get_platform_session),
) -> None:
    rate_limit.refuse_if_exhausted(request, "reset_password")
    try:
        async with session.begin():
            await password_service.complete_reset(
                session, raw_token=body.token, new_password=body.new_password, request=request
            )
    except ApiError as exc:
        # Guessing at tokens is the failure worth counting; a password that
        # is too weak is a person retyping, not an attack.
        if exc.code == CODE_INVALID_RESET_TOKEN:
            rate_limit.record_failure(request, "reset_password")
        raise


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(get_current_claims),
    session: AsyncSession = Depends(get_platform_session),
) -> None:
    """Changing your own password ends your other sessions — including the
    one you are using, which the client replaces by signing in again."""
    if claims.impersonated_by:
        # BR-AUTH-07: impersonation is for looking, not for taking over an
        # account. Changing the password would lock the real user out.
        raise ApiError(
            status.HTTP_403_FORBIDDEN,
            CODE_FORBIDDEN,
            "A password cannot be changed while impersonating this user",
        )
    await password_service.change_password(
        session,
        user_id=claims.user_id,
        current_password=body.current_password,
        new_password=body.new_password,
        request=request,
    )
    await session.commit()


async def _deliver(message_id) -> None:
    """Send a recorded message after its transaction committed. Shared shape
    with the invitation path; a failure is logged on the row, never raised."""
    import logging

    from sqlalchemy import text

    from app.core.db import PlatformSessionLocal
    from app.modules.notifications import email as email_service

    try:
        async with PlatformSessionLocal() as mail_session:
            row = (
                await mail_session.execute(
                    text(
                        "SELECT to_address, subject, body_preview, company_id "
                        "FROM outbound_messages WHERE id = :id"
                    ),
                    {"id": message_id},
                )
            ).mappings().first()
            config = await email_service.load_company_config(mail_session, row["company_id"]) if row else None
        if row is None:
            return
        sent, error = email_service.send(
            email_service.EmailMessageSpec(to=row["to_address"], subject=row["subject"], body=row["body_preview"]),
            config,
        )
        async with PlatformSessionLocal() as mail_session:
            await email_service.mark_result(mail_session, message_id=message_id, sent=sent, error=error)
            await mail_session.commit()
    except Exception:  # noqa: BLE001 — a failed send never fails the request
        logging.getLogger("app.auth.password").warning("Could not deliver reset email", exc_info=True)
