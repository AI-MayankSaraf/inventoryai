"""
Shared base class, naming convention, and helpers every model in
`02_DATABASE_DESIGN.md` is built from.

Read `02 §1` (global conventions) before adding a table. The short version,
encoded here so it cannot drift table-to-table:

  * PK is always `id UUID DEFAULT gen_random_uuid()`.
  * Tenant tables get `company_id UUID NOT NULL REFERENCES companies(id)`.
  * `(company_id, id)` is UNIQUE on every tenant table, so children can take
    a *composite* FK `(company_id, parent_id) -> (parent.company_id, parent.id)`
    instead of a plain FK on `id` alone. That composite FK is what makes it
    impossible to attach a row to the wrong tenant even if a single id is
    mis-set — §13 calls this out as the single most effective guard against
    cross-tenant leakage, so every intra-tenant reference uses it via
    `tenant_fk()` below. The exception: a reference to a table whose
    `company_id` can be NULL (`users`, `roles`, `documents`... — platform
    admins and system-wide rows) uses a plain FK on `id` instead, because a
    composite FK cannot match a NULL company_id. `plain_fk()` marks those.
  * Money is NUMERIC(18,2), unit prices/rates NUMERIC(18,4), quantities
    NUMERIC(18,3), percents NUMERIC(5,2) — see the `Money`/`Rate`/`Qty`/`Pct`
    type aliases below; never use these ad hoc with different precision.
  * Status/enum columns are TEXT + CHECK, never a native PG ENUM (see §1 for
    why) — use `enum_check()` to build the constraint.
  * created_at/updated_at/created_by/updated_by on every table via
    `AuditMixin`; `deleted_at` only on the master-data tables that are
    soft-deleted (§10) via `SoftDeleteMixin`; `row_version` only on editable
    business documents via `RowVersionMixin`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Numeric,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

def _fk_safe_name(constraint, table) -> str:
    """Custom naming-convention token (referenced as `%(fk_safe_name)s`
    below — SQLAlchemy's per-type keys like `"fk"` must stay %-format
    strings; a callable is only honoured on a *custom* token key). Same
    shape as the plain `"fk_<table>_<column>_<referred_table>"` pattern,
    run through `safe_identifier` — `plain_fk()` leaves its `ForeignKey`
    unnamed and relies on this convention, and a few of this schema's long
    table/column combinations (e.g.
    `document_schema_mapping_fields.canonical_field_id -> canonical_fields`)
    overrun Postgres's 63-byte identifier limit under the plain pattern."""
    cols = "_".join(col.name for col in constraint.columns)
    # `.target_fullname` reads the FK's declared string target ("documents.id")
    # without resolving/loading the referred Table — resolving it here would
    # break on any forward reference to a table not yet imported (this
    # schema has several: companies.logo_document_id -> documents, before
    # documents.py has necessarily been imported).
    referred = constraint.elements[0].target_fullname.split(".")[0] if constraint.elements else "x"
    return safe_identifier(f"fk_{table.name}_{cols}_{referred}")


# Alembic autogenerate and every manual migration key off these names, so a
# constraint always has the same name whether it was created by autogenerate
# or hand-written.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk_safe_name": _fk_safe_name,
    "fk": "%(fk_safe_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # §1: "Timestamps | TIMESTAMPTZ everywhere." Every bare `Mapped[datetime]`
    # column across every model gets this automatically — without it,
    # SQLAlchemy's default mapping for `datetime` is a naive
    # `TIMESTAMP WITHOUT TIME ZONE`, which is exactly the bug this line
    # exists to rule out everywhere in one place rather than per-column.
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


# ---------------------------------------------------------------- Type aliases
# 02 §1 "Money" / "Quantity" / "Percent" conventions, in one place so no table
# invents its own precision.
Money = Numeric(18, 2)
Rate = Numeric(18, 4)  # unit prices, purchase/sale price, mrp
Qty = Numeric(18, 3)
Pct = Numeric(5, 2)
Factor = Numeric(18, 6)  # UoM/pack conversion factors (§4, §5.9, §6.9)
Score = Numeric(6, 3)  # quotation_comparison_lines.recommendation_score (§6.7)
VariancePct = Numeric(9, 4)  # document_variances.difference_pct (§6.15)


import hashlib


def safe_identifier(name: str, limit: int = 63) -> str:
    """Postgres identifiers cap at 63 bytes. This model set concatenates
    table + column + parent-table names into constraint names, which for a
    few composite tenant FKs (e.g.
    `fk_ai_extraction_results_schema_mapping_id_document_schema_mappings`)
    overruns that — truncate deterministically with a short content hash so
    the name stays unique instead of silently colliding."""
    if len(name) <= limit:
        return name
    digest = hashlib.sha1(name.encode()).hexdigest()[:8]
    return f"{name[: limit - len(digest) - 1]}_{digest}"


def enum_check(column: str, values: list[str]) -> CheckConstraint:
    """`status TEXT NOT NULL` + `CHECK (status IN (...))` per §1 — never a
    native PG enum (value removal/reordering is painful; see §1)."""
    quoted = ", ".join(f"'{v}'" for v in values)
    return CheckConstraint(f"{column} IN ({quoted})", name=safe_identifier(f"{column}_valid"))


def tenant_fk(
    child_table: str,
    fk_column: str,
    parent_table: str,
    *,
    ondelete: str = "RESTRICT",
    use_alter: bool = False,
) -> ForeignKeyConstraint:
    """Composite tenant-scoped FK: `(company_id, fk_column)` ->
    `(parent_table.company_id, parent_table.id)`. Use for every reference to
    a NOT-NULL-company_id parent table (see module docstring). `fk_column`
    itself is declared as a bare `UUID` column with no per-column FK — the
    constraint lives here instead.

    `use_alter=True` is needed for the rare genuine *circular* dependency
    between two tenant tables (e.g. `alerts.variance_id -> document_variances`
    and `document_variances.alert_id -> alerts`) — same rationale as
    `plain_fk`'s always-on `use_alter=True`: it defers this constraint to a
    separate `ALTER TABLE ... ADD CONSTRAINT` batch after every table
    exists, so table-creation order no longer needs to resolve the cycle."""
    return ForeignKeyConstraint(
        ["company_id", fk_column],
        [f"{parent_table}.company_id", f"{parent_table}.id"],
        ondelete=ondelete,
        name=safe_identifier(f"fk_{child_table}_{fk_column}_{parent_table}"),
        use_alter=use_alter,
    )


def self_tenant_fk(
    table: str,
    fk_column: str,
    *,
    ondelete: str = "RESTRICT",
    deferrable: bool = False,
) -> ForeignKeyConstraint:
    """Composite tenant-scoped self-reference, e.g. `categories.parent_id`,
    `inventory_transactions.reverses_txn_id`. `deferrable` for a pair of
    rows that point at each other and are inserted together."""
    fk = tenant_fk(table, fk_column, table, ondelete=ondelete)
    if deferrable:
        fk.deferrable = True
    return fk


def plain_fk(target: str, *, ondelete: str = "RESTRICT", nullable: bool = True) -> Mapped:
    """For references to a table whose `company_id` can be NULL (`users`,
    `roles`, `documents`, `companies` itself) — a plain single-column FK,
    per the module docstring's exception rule.

    `use_alter=True` always: this whole model set has real *circular* table
    dependencies (`companies.created_by -> users.id`, but
    `users.company_id -> companies.id`; same for `documents`/`companies`
    logos and avatars). Alembic/SQLAlchemy resolve that automatically by
    emitting these as a separate `ALTER TABLE ... ADD CONSTRAINT` batch after
    every table exists, exactly like Postgres migrations that hit this in
    practice — no manual migration ordering needed."""
    return mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete, use_alter=True, name=None),
        nullable=nullable,
    )


def uq_company_id(table_name: str) -> UniqueConstraint:
    """`(company_id, id)` uniqueness that every composite FK into this table
    targets. Call once in every tenant table's `__table_args__`."""
    return UniqueConstraint("company_id", "id", name=f"uq_{table_name}_company_id_id")


# --------------------------------------------------------------------- Mixins
class UUIDPkMixin:
    """`id UUID NOT NULL DEFAULT gen_random_uuid() PRIMARY KEY` — §1. Never a
    sequential integer, never exposed as one."""

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )


class TenantMixin:
    """`company_id` on every tenant-owned table — always the first column of
    every composite index (§1, §12)."""

    company_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )


class AuditMixin:
    """`created_at`/`updated_at`/`created_by`/`updated_by` — §1. `updated_at`
    is bumped by a DB trigger (added in the RLS/triggers migration), not by
    the ORM, so it is correct even for a raw SQL `UPDATE`. `created_by`/
    `updated_by` reference `users.id` with `use_alter=True` (see `plain_fk`)
    because `users` itself carries an audit-mixin FK back through
    `company_id` — a real circular dependency, resolved the same way
    production Postgres migrations resolve it."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT", use_alter=True), nullable=True
    )
    updated_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT", use_alter=True), nullable=True
    )


class SoftDeleteMixin:
    """`deleted_at` — master-data tables only (§10). Transactional documents
    are cancelled, never deleted, and do not use this mixin."""

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )


class RowVersionMixin:
    """Optimistic locking on editable business documents (RFQ, PO, GRN,
    quotation, proforma, invoice) — §1."""

    row_version: Mapped[int] = mapped_column(nullable=False, server_default=text("1"))
