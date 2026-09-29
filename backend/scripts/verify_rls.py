"""
Proves Row-Level Security actually isolates tenants — on whatever database
this is pointed at, with whatever roles are configured there.

Run it after any migration, after changing database roles, and on any new
environment before it sees real data:

    python -m scripts.verify_rls

It creates two throwaway tenants, checks that neither can see the other's
rows through the ordinary app connection, and deletes them again. Nothing
is left behind. Exit code is 0 only if every check passes.

Why this exists rather than trusting that the policies are present: a
missing policy and a bypassed policy look identical from the application
side, and both look identical to "there is no data yet". `SELECT count(*)
FROM pg_policies` tells you the policies exist; only actually querying as a
restricted role tells you they *apply*.
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import text

from app.core.db import app_engine, platform_engine

_results: list[tuple[str, bool, str]] = []


def check(label: str, passed: bool, detail: str = "") -> None:
    _results.append((label, passed, detail))
    mark = "PASS" if passed else "FAIL"
    print(f"  {mark}  {label}" + (f"  ({detail})" if detail and not passed else ""))


async def describe_roles() -> bool:
    """Prints which role each engine connects as, and whether the runtime
    role is genuinely subject to RLS. This alone catches the worst
    misconfiguration (app pointed at a superuser)."""
    print("\nDatabase roles in use")
    ok = True

    async with platform_engine.connect() as conn:
        platform_role = (await conn.execute(text("SELECT current_user"))).scalar_one()
        print(f"  PLATFORM_DATABASE_URL -> {platform_role} (expected to bypass RLS)")

    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT current_user AS role_name, r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname = current_user"
                )
            )
        ).mappings().one()
        owns = (
            await conn.execute(
                text(
                    "SELECT pg_catalog.pg_get_userbyid(relowner) = current_user "
                    "FROM pg_class WHERE oid = 'public.companies'::regclass"
                )
            )
        ).scalar_one()
        print(f"  APP_DATABASE_URL      -> {row['role_name']} (must NOT bypass RLS)")
        if row["rolsuper"] or row["rolbypassrls"] or owns:
            why = []
            if row["rolsuper"]:
                why.append("superuser")
            if row["rolbypassrls"]:
                why.append("BYPASSRLS")
            if owns:
                why.append("owns the tenant tables")
            print(f"\n  !! '{row['role_name']}' bypasses RLS ({', '.join(why)}).")
            print("     Every isolation check below would pass vacuously. Fix APP_DATABASE_URL first.")
            ok = False
    return ok


async def main() -> int:
    roles_ok = await describe_roles()
    if not roles_ok:
        return 1

    suffix = uuid.uuid4().hex[:8]
    a_name, b_name = f"RLS Test A {suffix}", f"RLS Test B {suffix}"

    # Build two throwaway tenants through the platform (BYPASSRLS) role.
    async with platform_engine.begin() as conn:
        a_id = (
            await conn.execute(
                text(
                    "INSERT INTO companies (name, state_code, state_name) "
                    "VALUES (:n, '27', 'Maharashtra') RETURNING id"
                ),
                {"n": a_name},
            )
        ).scalar_one()
        b_id = (
            await conn.execute(
                text(
                    "INSERT INTO companies (name, state_code, state_name) "
                    "VALUES (:n, '07', 'Delhi') RETURNING id"
                ),
                {"n": b_name},
            )
        ).scalar_one()
        a_godown = (
            await conn.execute(
                text("INSERT INTO godowns (company_id, name) VALUES (:c, 'A Warehouse') RETURNING id"),
                {"c": a_id},
            )
        ).scalar_one()
        b_godown = (
            await conn.execute(
                text("INSERT INTO godowns (company_id, name) VALUES (:c, 'B Warehouse') RETURNING id"),
                {"c": b_id},
            )
        ).scalar_one()

    print("\nTenant isolation")
    try:
        # 1. No tenant context at all -> must see nothing (fail closed).
        async with app_engine.connect() as conn:
            visible = (
                await conn.execute(
                    text("SELECT count(*) FROM godowns WHERE id IN (:a, :b)"),
                    {"a": a_godown, "b": b_godown},
                )
            ).scalar_one()
            check("no tenant context -> sees nothing (fails closed, not open)", visible == 0, f"saw {visible}")

        # 2/3. Each tenant sees only its own rows.
        for label, own_id, own_godown, other_godown in (
            ("A", a_id, a_godown, b_godown),
            ("B", b_id, b_godown, a_godown),
        ):
            async with app_engine.connect() as conn:
                await conn.execute(
                    text("SELECT set_config('app.current_company_id', :c, true)"),
                    {"c": str(own_id)},
                )
                sees_own = (
                    await conn.execute(
                        text("SELECT count(*) FROM godowns WHERE id = :g"), {"g": own_godown}
                    )
                ).scalar_one()
                sees_other = (
                    await conn.execute(
                        text("SELECT count(*) FROM godowns WHERE id = :g"), {"g": other_godown}
                    )
                ).scalar_one()
                check(f"tenant {label} sees its own godown", sees_own == 1, f"saw {sees_own}")
                check(f"tenant {label} cannot see the other tenant's godown", sees_other == 0, f"saw {sees_other}")

                own_companies = (
                    await conn.execute(text("SELECT count(*) FROM companies"))
                ).scalar_one()
                check(f"tenant {label} sees exactly one company row (its own)", own_companies == 1, f"saw {own_companies}")

        # 4. Writing a row that claims another tenant must be refused.
        async with app_engine.connect() as conn:
            trans = await conn.begin()
            await conn.execute(
                text("SELECT set_config('app.current_company_id', :c, true)"), {"c": str(a_id)}
            )
            try:
                await conn.execute(
                    text("INSERT INTO godowns (company_id, name) VALUES (:c, 'Cross-tenant write')"),
                    {"c": str(b_id)},
                )
                check("cross-tenant INSERT is refused", False, "the insert succeeded")
            except Exception as exc:  # noqa: BLE001 — any refusal is a pass
                check("cross-tenant INSERT is refused", "row-level security" in str(exc).lower(), str(exc)[:80])
            finally:
                await trans.rollback()

        # 5. Shared system reference data stays visible to every tenant.
        async with app_engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.current_company_id', :c, true)"), {"c": str(a_id)}
            )
            system_roles = (
                await conn.execute(text("SELECT count(*) FROM roles WHERE company_id IS NULL"))
            ).scalar_one()
            check("system roles (company_id IS NULL) remain visible to tenants", system_roles == 7, f"saw {system_roles}")

        # 6. Platform-only tables stay invisible to tenant connections.
        async with app_engine.connect() as conn:
            await conn.execute(
                text("SELECT set_config('app.current_company_id', :c, true)"), {"c": str(a_id)}
            )
            tokens = (await conn.execute(text("SELECT count(*) FROM refresh_tokens"))).scalar_one()
            check("refresh_tokens invisible to tenant connections (deny-all)", tokens == 0, f"saw {tokens}")

    finally:
        async with platform_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM godowns WHERE id IN (:a, :b)"), {"a": a_godown, "b": b_godown}
            )
            await conn.execute(
                text("DELETE FROM companies WHERE id IN (:a, :b)"), {"a": a_id, "b": b_id}
            )
        await app_engine.dispose()
        await platform_engine.dispose()

    passed = sum(1 for _, ok, _ in _results if ok)
    total = len(_results)
    print(f"\n{passed}/{total} checks passed")
    if passed != total:
        print("\nRLS is NOT isolating tenants correctly. Do not put real data in this database.")
        return 1
    print("Tenant isolation is enforced by the database, not just by application code.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
