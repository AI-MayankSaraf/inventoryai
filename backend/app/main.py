"""
FastAPI application entrypoint.

App boot, settings, DB wiring, a health check that proves the app can reach
Postgres and see the migrated schema, and the routers built so far (auth,
catalog). Also home to the RLS safety check described in
`assert_app_role_is_rls_bound` below, which runs before the app will serve
a single request.
"""

import asyncio
import contextlib
from contextlib import asynccontextmanager

import anyio.to_thread

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core import audit, storage
from app.core.config import get_settings
from app.core.errors import (
    ApiError,
    api_error_handler,
    http_exception_handler,
    validation_exception_handler,
)
from app.core.db import PlatformSessionLocal, app_engine, engine
from app.core.security import decode_access_token
from app.modules.auth.router import router as auth_router
from app.modules.auth.users_router import router as users_router
from app.modules.catalog.detail_router import router as catalog_detail_router
from app.modules.catalog.router import router as catalog_router
from app.modules.ai import worker as extraction_worker
from app.modules.ai.router import router as ai_router
from app.modules.supplier_portal.router import router as supplier_portal_router
from app.modules.documents.router import router as documents_router
from app.modules.inventory.router import router as inventory_router
from app.modules.ops.router import router as ops_router
from app.modules.platform.admin_router import router as platform_admin_router
from app.modules.platform.console_router import router as platform_console_router
from app.modules.platform.router import router as company_router
from app.modules.platform.lists_router import router as company_lists_router
from app.modules.procurement.router import router as procurement_router

settings = get_settings()


class UnsafeDatabaseRoleError(RuntimeError):
    """Raised at startup when the runtime database role would bypass RLS."""


async def assert_app_role_is_rls_bound() -> None:
    """Refuse to start if `APP_DATABASE_URL`'s role can bypass Row-Level
    Security.

    This guards the single most dangerous misconfiguration in the whole
    system, and the only one that fails *silently*. Postgres exempts three
    kinds of role from RLS: superusers (always, and `FORCE ROW LEVEL
    SECURITY` does not stop them), roles with the BYPASSRLS attribute, and
    the table's own owner. Point the app at any of those — say, at the same
    superuser connection string used for migrations — and every
    `tenant_isolation` policy is skipped without a single error or log
    line. The app keeps working perfectly; it just serves every tenant's
    data to every tenant.

    Nothing in normal operation would reveal that. An empty result set
    looks the same whether isolation is enforced or absent, so the failure
    surfaces the first time a customer sees another customer's purchase
    orders. Hence: check once, at boot, and refuse to serve rather than
    serve unsafely.

    Note this deliberately checks the *runtime* role only. `DATABASE_URL`
    (Alembic) and `PLATFORM_DATABASE_URL` (seeding, auth lookups) are both
    supposed to bypass RLS — that's their job.
    """
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT current_user AS role_name, "
                    "       r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            )
        ).mappings().first()

        if row is None:  # pragma: no cover — current_user always resolves
            raise UnsafeDatabaseRoleError("Could not determine the app's database role")

        role_name = row["role_name"]
        reasons = []
        if row["rolsuper"]:
            reasons.append("it is a superuser")
        if row["rolbypassrls"]:
            reasons.append("it has the BYPASSRLS attribute")

        # The owner exemption is per-table, so check a representative
        # tenant table rather than a role attribute.
        owns_tenant_tables = (
            await conn.execute(
                text("SELECT pg_catalog.pg_get_userbyid(relowner) = current_user "
                     "FROM pg_class WHERE oid = 'public.companies'::regclass")
            )
        ).scalar_one()
        if owns_tenant_tables:
            reasons.append("it owns the tenant tables (owners are exempt unless FORCE ROW LEVEL SECURITY is set)")

    if reasons:
        raise UnsafeDatabaseRoleError(
            f"APP_DATABASE_URL connects as '{role_name}', which bypasses Row-Level Security because "
            f"{', and '.join(reasons)}. Every tenant-isolation policy would be silently skipped and "
            f"the API would serve every tenant's data to every caller.\n\n"
            f"Fix: point APP_DATABASE_URL at a role that is not a superuser, does not have BYPASSRLS, "
            f"and does not own the tables — e.g. 'inventoryai_app' from BACKEND-SETUP.md. "
            f"Superuser/owner connections belong in DATABASE_URL (migrations) only."
        )


class InsecureConfigurationError(RuntimeError):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Weak or default secrets (any environment — security audit H5), or
    # DEBUG outside development: refuse to serve at all.
    problems = settings.production_problems()
    if problems:
        raise InsecureConfigurationError(
            f"ENVIRONMENT={settings.environment}: this configuration is not safe to run:\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n\nKeep secrets in Secrets Manager:  python -m scripts.secrets_manager push"
            + "\n(Throwaway local database only: ALLOW_DEV_SECRET=true skips the secret checks.)"
        )
    # Fail fast on boot if the DB is unreachable, rather than on first request.
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    await assert_app_role_is_rls_bound()
    # Same reasoning, one layer out: object storage has no local-disk
    # fallback by design (BR-DOC-03), so a missing bucket or a bad
    # credential must stop the process now rather than surface as a 500 the
    # first time somebody uploads a supplier's invoice. Checked with
    # HeadBucket, which needs no write and creates nothing.
    await anyio.to_thread.run_sync(storage.assert_ready)
    # Uploaded documents are read by a worker; unless a separate worker
    # process does it (EXTRACTION_WORKER=external), this process runs one.
    worker_task = None
    if settings.extraction_worker == "embedded":
        worker_task = asyncio.create_task(extraction_worker.run_forever(), name="extraction-worker")
    yield
    if worker_task is not None:
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task
    await engine.dispose()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

# The frontend runs on its own origin (Next.js dev server), so every fetch
# it makes is cross-origin from the browser's perspective. `allow_credentials`
# is deliberately off — auth is a bearer token in the `Authorization` header,
# never a cookie, so there is nothing here for a CSRF-style attack to ride.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origin_list,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Validation errors get the same envelope. `ApiError` is deliberately NOT
# registered separately: it subclasses HTTPException, and a dedicated
# handler would route it around the denial-auditing handler below — which
# is precisely where GODOWN_OUT_OF_SCOPE and ROLE_ESCALATION 403s live.
app.add_exception_handler(RequestValidationError, validation_exception_handler)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(catalog_router)
app.include_router(catalog_detail_router)
app.include_router(company_router)
app.include_router(company_lists_router)
app.include_router(platform_admin_router)
app.include_router(platform_console_router)
app.include_router(procurement_router)
app.include_router(inventory_router)
app.include_router(ops_router)
app.include_router(documents_router)
app.include_router(ai_router)
app.include_router(supplier_portal_router)


@app.exception_handler(HTTPException)
async def audit_permission_denials(request: Request, exc: HTTPException):
    """06_BUSINESS_RULES.md §15 requires "every permission denial" to be
    audited, and §6 of the RBAC matrix adds that "repeated denials raise a
    security alert" — which needs the denials on record first.

    A denial is raised by `require_permission` before the handler runs, so
    there is no request-scoped session to write through and nothing to roll
    back. This writes through its own short-lived platform-engine session:
    the event is a security record rather than tenant data, and an
    exception path is the wrong place to be juggling tenant context.

    Handles `ApiError` too, since that subclasses HTTPException — which is
    the point: a scope or escalation denial is exactly the kind of event
    §15 wants recorded, and routing those through a separate handler would
    have quietly skipped them.

    The audit write is best-effort — a failure here must not turn a clean
    403 into a 500, because the caller still needs to be refused.
    """
    if exc.status_code == status.HTTP_403_FORBIDDEN:
        try:
            claims = None
            auth_header = request.headers.get("authorization", "")
            if auth_header.lower().startswith("bearer "):
                try:
                    claims = decode_access_token(auth_header.split(" ", 1)[1])
                except JWTError:
                    claims = None

            async with PlatformSessionLocal() as session:
                async with session.begin():
                    await audit.record(
                        session,
                        entity_type="permission",
                        action="permission_denied",
                        claims=claims,
                        description=f"{request.method} {request.url.path}: {exc.detail}",
                        request=request,
                    )
        except Exception:  # noqa: BLE001 — never let auditing break the response
            pass

    if isinstance(exc, ApiError):
        return await api_error_handler(request, exc)
    return await http_exception_handler(request, exc)


async def _schema_snapshot(conn: AsyncConnection) -> dict:
    table_count = (
        await conn.execute(
            text(
                "SELECT count(*) FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'"
            )
        )
    ).scalar_one()
    alembic_version = (
        await conn.execute(text("SELECT version_num FROM alembic_version"))
    ).scalar_one_or_none()
    extensions = [
        row[0]
        for row in (await conn.execute(text("SELECT extname FROM pg_extension ORDER BY extname"))).all()
    ]
    rls_tables = (
        await conn.execute(
            text(
                "SELECT count(*) FROM pg_class "
                "WHERE relkind = 'r' AND relnamespace = 'public'::regnamespace AND relrowsecurity"
            )
        )
    ).scalar_one()
    return {
        "table_count": table_count,
        "alembic_version": alembic_version,
        "extensions": extensions,
        "rls_enabled_tables": rls_tables,
    }


@app.get("/health")
async def health() -> dict:
    """Liveness + a real round-trip to Postgres. Not just "the process is
    up" — it proves the app can query the actual migrated schema, and
    reports how many tables have RLS switched on."""
    async with engine.connect() as conn:
        snapshot = await _schema_snapshot(conn)
    return {
        "status": "ok",
        "app": settings.app_name,
        "environment": settings.environment,
        "database": snapshot,
    }


@app.get("/")
async def root() -> dict:
    return {"app": settings.app_name, "status": "ok", "docs": "/docs"}
