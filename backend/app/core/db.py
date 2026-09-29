"""
Async SQLAlchemy engines/sessions and the per-request tenant-scoping helper.

Three engines, matching the three Postgres roles described in
`app/core/config.py` and `alembic/versions/..._rls_policies.py`:

  * `owner_engine` — the schema-owning role. Alembic migrates with this
    (via `alembic/env.py`, independently of this module). It bypasses RLS
    by default because it owns every table. Not used by request handling.
  * `app_engine` — every ordinary per-request tenant session uses this.
    NOT the table owner, NOT BYPASSRLS, so its queries are actually
    subject to the RLS policies. `get_session()` + `set_tenant()` below are
    built on this engine.
  * `platform_engine` — BYPASSRLS, for the handful of things that
    legitimately need to see across tenants: seeding (`app/db/seed.py`),
    auth/refresh-token lookups (which happen before any tenant is known —
    you can't know which tenant a bearer token belongs to until you've
    already looked it up), and impersonation.

Every request transaction that touches a tenant table must call
`set_tenant(session, company_id)` first, which scopes the RLS policies to
that tenant for the rest of the transaction. A platform-admin request
instead gets its session from `get_platform_session()`, which needs no
`SET LOCAL` at all — BYPASSRLS makes the tenant filter irrelevant.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

owner_engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

app_engine = create_async_engine(
    settings.app_database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

platform_engine = create_async_engine(
    settings.platform_database_url,
    echo=settings.database_echo,
    pool_pre_ping=True,
)

# Back-compat alias: existing call sites (main.py's health check, which just
# does read-only catalog queries unaffected by RLS) import `engine`.
engine = app_engine

AppSessionLocal = async_sessionmaker(bind=app_engine, expire_on_commit=False, autoflush=False)
PlatformSessionLocal = async_sessionmaker(bind=platform_engine, expire_on_commit=False, autoflush=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """Ordinary per-request session, RLS-restricted. The caller must still
    call `set_tenant()` before touching a tenant table — this dependency
    alone does not scope anything."""
    async with AppSessionLocal() as session:
        yield session


async def get_platform_session() -> AsyncIterator[AsyncSession]:
    """BYPASSRLS session for platform-admin/service-level operations (auth
    token lookups, impersonation, cross-tenant platform endpoints)."""
    async with PlatformSessionLocal() as session:
        yield session


async def set_tenant(session: AsyncSession, company_id: UUID) -> None:
    """Scope the rest of this transaction to one tenant. RLS policies key off
    `current_setting('app.current_company_id', true)`.

    Uses `set_config(name, value, is_local => true)` rather than
    `SET LOCAL app.current_company_id = :company_id` — Postgres's `SET`
    statement does not accept a bind parameter in the value position over
    the extended query protocol (`SET LOCAL ... = $1` is a syntax error),
    so `SET LOCAL` can only take a literal, which would mean
    string-formatting a company_id into SQL text. `set_config()` is a
    regular function call and takes its second argument as a normal bind
    parameter; `is_local => true` gives it the exact same
    transaction-scoped-only behaviour as `SET LOCAL`, so connection pooling
    can never leak one request's tenant into the next.
    """
    await session.execute(
        text("SELECT set_config('app.current_company_id', :company_id, true)"),
        {"company_id": str(company_id)},
    )


async def commit_and_rescope(session: AsyncSession, company_id: UUID) -> None:
    """Commit, then re-assert the tenant scope the commit just dropped.

    Use this instead of a bare `session.commit()` in any service that
    commits and then *reads back* on the same session.

    Why this exists: `set_tenant()` uses `set_config(..., is_local => true)`,
    which is transaction-scoped by design -- that is what stops connection
    pooling from leaking one request's tenant into the next. The cost is
    that committing ends the scope, so the very next statement runs with
    `app.current_company_id` unset and every RLS policy evaluates
    `''::uuid`, failing with "invalid input syntax for type uuid: ''".

    That failure has now been rediscovered in four separate modules
    (comparison, inventory, documents, alerts), always the same way: a
    service commits its unit of work and then re-loads the row to return
    it. The pattern is correct; it just needs this one line after it, so it
    is a function rather than a comment repeated in each service.
    """
    await session.commit()
    await set_tenant(session, company_id)
