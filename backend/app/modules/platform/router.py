"""
Company profile and settings — the `/settings` screen's backend.

Two resources on one company row: the profile (legal name, GSTIN, address
— what appears on printed documents) and the settings (25 configuration
flags that drive business rules elsewhere: approval thresholds,
variance tolerances, AI confidence cut-offs, alert preferences).

Both are gated on `company.view` / `company.manage`, and `company.manage`
is Owner-only per 07_RBAC_MATRIX.md ("Edit company settings" and "Edit
GSTIN / numbering" are ✓ for Owner and ✗ for every other role). The RBAC
matrix also asks that Settings be "read-only for non-Owners rather than
hidden, so the team can see the configuration" — hence the split: everyone
gets `company.view`, only the Owner gets `company.manage`.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit
from app.core.db import commit_and_rescope
from app.core.deps import get_tenant_session, require_permission
from app.core.security import AccessTokenClaims
from app.modules.notifications import email as email_service
from app.modules.notifications.email import secrets_key as _secrets_key
from app.modules.platform.schemas import (
    CompanyProfileOut,
    CompanyProfileUpdate,
    CompanySettingsOut,
    CompanySettingsUpdate,
    DocumentSequenceOut,
    EmailSettingsOut,
    EmailSettingsUpdate,
    EmailTestRequest,
    EmailTestResult,
    GodownUsageOut,
)

router = APIRouter(prefix="/company", tags=["company"])

_PROFILE_COLUMNS = [
    "id", "name", "legal_name", "gstin", "pan", "state_code", "state_name",
    "city", "address_line1", "address_line2", "pincode", "email", "phone",
    "plan", "status", "onboarded_on",
]

_SETTINGS_COLUMNS = [
    "company_id", "currency_code", "default_gst_rate", "rounding_mode",
    "financial_year_start_month", "default_godown_id", "ai_auto_process",
    "ai_review_confidence_threshold", "ai_suggest_while_typing",
    "ai_never_autoapprove_financials", "low_stock_threshold_mode",
    "alert_email_critical", "alert_daily_low_stock_digest", "alert_po_delay_notify",
    "po_delay_grace_days", "allow_grn_excess_receipt", "grn_excess_tolerance_pct",
    "require_po_approval_above", "require_maker_checker", "allow_negative_stock",
    "allow_nonstandard_gst", "inventory_locked_through",
    "variance_price_tolerance_pct", "variance_amount_tolerance", "comparison_weights",
]


@router.get("/profile", response_model=CompanyProfileOut)
async def get_profile(
    claims: AccessTokenClaims = Depends(require_permission("company.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    row = (
        await session.execute(
            text(f"SELECT {', '.join(_PROFILE_COLUMNS)} FROM companies WHERE id = :c"),
            {"c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found")
    return dict(row)


@router.patch("/profile", response_model=CompanyProfileOut)
async def update_profile(
    body: CompanyProfileUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    before = await _fetch(session, "companies", _PROFILE_COLUMNS, "id", claims.company_id)
    values = body.model_dump(exclude_unset=True)
    if not values:
        return before

    assignments = ", ".join(f"{k} = :{k}" for k in values)
    values["c"] = claims.company_id
    row = (
        await session.execute(
            text(f"UPDATE companies SET {assignments} WHERE id = :c RETURNING {', '.join(_PROFILE_COLUMNS)}"),
            values,
        )
    ).mappings().first()

    after = dict(row)
    await audit.record(
        session,
        entity_type="company",
        action="updated",
        claims=claims,
        entity_id=after["id"],
        entity_label=after["name"],
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


@router.get("/settings", response_model=CompanySettingsOut)
async def get_settings_(
    claims: AccessTokenClaims = Depends(require_permission("company.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    row = (
        await session.execute(
            text(f"SELECT {', '.join(_SETTINGS_COLUMNS)} FROM company_settings WHERE company_id = :c"),
            {"c": claims.company_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="This company has no settings row; it was created outside the normal onboarding flow",
        )
    return dict(row)


@router.patch("/settings", response_model=CompanySettingsOut)
async def update_settings(
    body: CompanySettingsUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    before = await _fetch(session, "company_settings", _SETTINGS_COLUMNS, "company_id", claims.company_id)
    values = body.model_dump(exclude_unset=True)
    if not values:
        return before

    if "default_godown_id" in values and values["default_godown_id"] is not None:
        # Not just referential integrity — RLS would already stop a
        # cross-tenant id — but so the error is a readable 400 rather than
        # a foreign-key 500.
        exists = (
            await session.execute(
                text("SELECT 1 FROM godowns WHERE id = :g AND company_id = :c AND deleted_at IS NULL"),
                {"g": values["default_godown_id"], "c": claims.company_id},
            )
        ).first()
        if exists is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unknown godown")

    assignments = ", ".join(f"{k} = :{k}" for k in values)
    values["c"] = claims.company_id
    row = (
        await session.execute(
            text(
                f"UPDATE company_settings SET {assignments} WHERE company_id = :c "
                f"RETURNING {', '.join(_SETTINGS_COLUMNS)}"
            ),
            values,
        )
    ).mappings().first()

    after = dict(row)
    await audit.record(
        session,
        entity_type="settings",
        action="updated",
        claims=claims,
        entity_id=None,
        entity_label="Company settings",
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


async def _fetch(
    session: AsyncSession, table: str, columns: list[str], key: str, value: Optional[str]
) -> dict:
    row = (
        await session.execute(
            text(f"SELECT {', '.join(columns)} FROM {table} WHERE {key} = :v"), {"v": value}
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{table} row not found")
    return dict(row)


# ================================================= numbering and godowns

@router.get("/document-sequences", response_model=list[DocumentSequenceOut])
async def list_document_sequences(
    claims: AccessTokenClaims = Depends(require_permission("company.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    """The live numbering series.

    Read-only. The allocator owns `next_number`, and letting a screen set it
    is how two documents end up sharing a number: the counter is claimed
    inside the same transaction that writes the document, so anything that
    edits it from outside is racing the thing it is trying to configure.
    Changing a prefix mid-year has the same problem from the other end — the
    series is unique per (doc_type, financial_year), so a new prefix belongs
    to a new year, not a retroactive edit.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, doc_type, financial_year, prefix, padding, next_number "
                "FROM document_sequences WHERE company_id = :c "
                "ORDER BY financial_year DESC, doc_type"
            ),
            {"c": claims.company_id},
        )
    ).mappings().all()
    return [dict(r) for r in rows]


_USAGE_SQL = """
    SELECT g.id AS godown_id,
           iu.full_name AS incharge_name,
           COALESCE(s.sku_count, 0)   AS sku_count,
           COALESCE(s.stock_value, 0) AS stock_value,
           COALESCE(po.open_count, 0) AS open_po_count,
           COALESCE(u.scoped_count, 0) AS scoped_user_count
      FROM godowns g
      LEFT JOIN users iu ON iu.id = g.incharge_user_id
      LEFT JOIN LATERAL (
           SELECT COUNT(*) AS sku_count,
                  ROUND(SUM(sb.quantity * COALESCE(pv.purchase_price, 0)), 2) AS stock_value
             FROM stock_balances sb
             JOIN product_variants pv
               ON pv.id = sb.product_variant_id AND pv.company_id = sb.company_id
            WHERE sb.godown_id = g.id
              AND sb.company_id = g.company_id
              AND sb.quantity > 0
              AND pv.deleted_at IS NULL
      ) s ON TRUE
      LEFT JOIN LATERAL (
           SELECT COUNT(*) AS open_count
             FROM purchase_orders p
            WHERE p.delivery_godown_id = g.id
              AND p.company_id = g.company_id
              AND p.status NOT IN ('closed', 'cancelled', 'draft')
      ) po ON TRUE
      LEFT JOIN LATERAL (
           SELECT COUNT(DISTINCT ug.user_id) AS scoped_count
             FROM user_godown_access ug
             JOIN users usr ON usr.id = ug.user_id AND usr.deleted_at IS NULL
            WHERE ug.godown_id = g.id
      ) u ON TRUE
     WHERE g.company_id = :c
       -- Godowns are soft-deleted. Without this a deleted godown kept its
       -- row here with whatever counts it had, so usage and the godown list
       -- disagreed about how many godowns exist.
       AND g.deleted_at IS NULL
"""


def _usage_row(row: dict) -> dict:
    """Turn the counts into the one answer the Godowns screen needs.

    Order matters: stock is the reason a user is most likely to be able to
    act on ("move it, then deactivate"), so it is named first.
    """
    out = dict(row)
    out["stock_value"] = float(out["stock_value"] or 0)
    reason = None
    if out["sku_count"]:
        reason = f"{out['sku_count']} item(s) still in stock here"
    elif out["open_po_count"]:
        reason = f"{out['open_po_count']} open purchase order(s) deliver here"
    elif out["scoped_user_count"]:
        reason = f"{out['scoped_user_count']} user(s) are scoped to this godown"
    out["reason"] = reason
    out["in_use"] = reason is not None
    return out


@router.get("/godown-usage", response_model=list[GodownUsageOut])
async def list_godown_usage(
    claims: AccessTokenClaims = Depends(require_permission("godown.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> list[dict]:
    """Usage for every godown in one round trip.

    The Godowns list shows SKU count and stock value per row, so doing this
    per godown would be one request per row.
    """
    rows = (
        await session.execute(text(_USAGE_SQL + " ORDER BY g.name"), {"c": claims.company_id})
    ).mappings().all()
    return [_usage_row(dict(r)) for r in rows]


@router.get("/godown-usage/{godown_id}", response_model=GodownUsageOut)
async def godown_usage(
    godown_id: UUID,
    claims: AccessTokenClaims = Depends(require_permission("godown.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """The deactivation guard for one godown."""
    row = (
        await session.execute(
            text(_USAGE_SQL + " AND g.id = :id"),
            {"c": claims.company_id, "id": godown_id},
        )
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Godown not found")
    return _usage_row(dict(row))


# ==================================================== email / SMTP settings

_EMAIL_COLUMNS = (
    "company_id, provider, from_address, from_name, smtp_host, smtp_port, smtp_username, smtp_use_tls, "
    "(smtp_password_encrypted IS NOT NULL) AS has_password, last_test_at, last_test_ok, last_test_error"
)


def _default_email_settings(company_id) -> dict:
    """What a tenant that has never configured email looks like. No row is
    written until someone saves — an empty table means "nobody has touched
    this", which is worth being able to tell."""
    return {
        "company_id": company_id,
        "provider": "console",
        "from_address": None,
        "from_name": None,
        "smtp_host": None,
        "smtp_port": 587,
        "smtp_username": None,
        "smtp_use_tls": True,
        "has_password": False,
        "last_test_at": None,
        "last_test_ok": None,
        "last_test_error": None,
    }


async def _email_settings(session: AsyncSession, company_id) -> dict:
    row = (
        await session.execute(
            text(f"SELECT {_EMAIL_COLUMNS} FROM company_email_settings WHERE company_id = :c"),
            {"c": company_id},
        )
    ).mappings().first()
    return dict(row) if row else _default_email_settings(company_id)


@router.get("/email-settings", response_model=EmailSettingsOut)
async def get_email_settings(
    claims: AccessTokenClaims = Depends(require_permission("company.view")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """Where this company's invitations and password-reset links are sent
    from. The SMTP password is write-only — this reports only whether one is
    stored."""
    return await _email_settings(session, claims.company_id)


@router.put("/email-settings", response_model=EmailSettingsOut)
async def update_email_settings(
    body: EmailSettingsUpdate,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    before = await _email_settings(session, claims.company_id)
    values = body.model_dump()
    password = values.pop("smtp_password")

    params = {
        **values,
        "c": claims.company_id,
        "by": claims.user_id,
        "key": _secrets_key(),
        "password": password,
    }
    # Three cases for the password, and they are genuinely different:
    # omitted (None) keeps what is stored, "" clears it, anything else
    # replaces it — encrypted with pgcrypto, never readable from the API.
    if password is None:
        password_sql = "smtp_password_encrypted = company_email_settings.smtp_password_encrypted"
        insert_password = "NULL"
    elif password == "":
        password_sql = "smtp_password_encrypted = NULL"
        insert_password = "NULL"
    else:
        password_sql = "smtp_password_encrypted = pgp_sym_encrypt(:password, :key)"
        insert_password = "pgp_sym_encrypt(:password, :key)"

    await session.execute(
        text(
            "INSERT INTO company_email_settings (company_id, provider, from_address, from_name, smtp_host, "
            " smtp_port, smtp_username, smtp_password_encrypted, smtp_use_tls, updated_at, updated_by) "
            f"VALUES (:c, :provider, :from_address, :from_name, :smtp_host, :smtp_port, :smtp_username, "
            f" {insert_password}, :smtp_use_tls, now(), :by) "
            "ON CONFLICT (company_id) DO UPDATE SET provider = EXCLUDED.provider, "
            " from_address = EXCLUDED.from_address, from_name = EXCLUDED.from_name, "
            " smtp_host = EXCLUDED.smtp_host, smtp_port = EXCLUDED.smtp_port, "
            " smtp_username = EXCLUDED.smtp_username, smtp_use_tls = EXCLUDED.smtp_use_tls, "
            f" {password_sql}, updated_at = now(), updated_by = EXCLUDED.updated_by"
        ),
        params,
    )

    after = await _email_settings(session, claims.company_id)
    await audit.record(
        session,
        entity_type="settings",
        action="updated",
        claims=claims,
        entity_id=UUID(claims.company_id),
        entity_label="Email settings",
        description="Outgoing email settings changed",
        before=before,
        after=after,
        request=request,
    )
    await session.commit()
    return after


@router.post("/email-settings/test", response_model=EmailTestResult)
async def test_email_settings(
    body: EmailTestRequest,
    request: Request,
    claims: AccessTokenClaims = Depends(require_permission("company.manage")),
    session: AsyncSession = Depends(get_tenant_session),
) -> dict:
    """Send one test message with the *saved* settings and record what
    happened. Deliberately uses what is stored rather than what is on the
    form: the question being answered is "will invitations actually arrive",
    and those will use the stored row."""
    to_address = body.to_address
    if not to_address:
        to_address = (
            await session.execute(text("SELECT email FROM users WHERE id = :u"), {"u": claims.user_id})
        ).scalar_one()
    company_name = (
        await session.execute(text("SELECT name FROM companies WHERE id = :c"), {"c": claims.company_id})
    ).scalar_one_or_none() or "your company"

    config = await email_service.load_company_config(session, claims.company_id)
    spec = email_service.test_email(company_name=company_name)
    spec.to = to_address
    message_id = await email_service.record_outbound(
        session,
        company_id=claims.company_id,
        message_type="alert_digest",  # closest allowed type; the subject says what it is
        to_address=to_address,
        subject=spec.subject,
        body_preview=spec.body,
        sent_by=claims.user_id,
    )
    await session.commit()

    sent, error = email_service.send(spec, config)

    await commit_and_rescope(session, UUID(claims.company_id))
    await email_service.mark_result(session, message_id=message_id, sent=sent, error=error)
    await session.execute(
        text(
            "INSERT INTO company_email_settings (company_id, last_test_at, last_test_ok, last_test_error) "
            "VALUES (:c, now(), :ok, :error) ON CONFLICT (company_id) DO UPDATE SET "
            "last_test_at = now(), last_test_ok = EXCLUDED.last_test_ok, last_test_error = EXCLUDED.last_test_error"
        ),
        {"c": claims.company_id, "ok": sent, "error": error},
    )
    await session.commit()

    return {"sent": sent, "provider": config.provider, "to_address": to_address, "error": error}
