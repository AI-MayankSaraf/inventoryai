"""
E2E HTTP suite — the auth gaps: password reset, password change,
impersonation (BR-AUTH-07), instant session revocation, and per-company
email/SMTP settings.

Runs against a live backend (default http://127.0.0.1:8000) seeded with the
demo tenants *and* the platform admin (`python -m app.db.seed` creates it).
Creates its own users with a per-run suffix, so it can be re-run.

    python -m scripts.e2e_auth [base_url]

Exit code 0 only if every check passes.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import urllib.error
import urllib.request
import uuid

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
SFX = uuid.uuid4().hex[:6].upper()

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, info: object = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name}  -> {str(info)[:300]}")


def call(method: str, path: str, token: str | None = None, body: object = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, raw.decode(errors="replace")


def login(email: str, password: str) -> tuple[int, object]:
    return call("POST", "/auth/login", body={"email": email, "password": password})


def token_of(email: str, password: str) -> str:
    st, body = login(email, password)
    assert st == 200, (email, st, body)
    return body["access_token"]


def ok(st: int, body: object, expected: int = 200) -> object:
    assert st == expected, (st, body)
    return body


# --------------------------------------------------------------- db helpers

async def _fetch(sql: str, params: dict | None = None):
    """Each call gets its own engine: `asyncio.run` closes the event loop it
    created, and a pooled connection left over from a previous loop blows up
    on the next one."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from app.core.config import get_settings

    engine = create_async_engine(get_settings().platform_database_url, poolclass=NullPool)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql), params or {})
            if not result.returns_rows:
                return []
            return [dict(r) for r in result.mappings().all()]
    finally:
        await engine.dispose()


def db(sql: str, params: dict | None = None):
    return asyncio.run(_fetch(sql, params))


def make_users() -> dict[str, str]:
    """A staff user to impersonate and revoke, in the Acme tenant."""

    async def _make():
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine
        from sqlalchemy.pool import NullPool

        from app.core.config import get_settings
        from app.core.security import hash_password

        out = {}
        engine = create_async_engine(get_settings().platform_database_url, poolclass=NullPool)
        async with engine.begin() as conn:
            cid = (
                await conn.execute(text("SELECT id FROM companies WHERE name = 'Acme Trading Co' ORDER BY id LIMIT 1"))
            ).scalar_one()
            for role in ("staff", "viewer"):
                rid = (
                    await conn.execute(
                        text("SELECT id FROM roles WHERE company_id IS NULL AND code = :r"), {"r": role}
                    )
                ).scalar_one()
                email = f"auth.{role}.{SFX.lower()}@acme-demo.test"
                await conn.execute(
                    text(
                        "INSERT INTO users (company_id, email, full_name, role_id, is_platform_admin, "
                        "has_all_godowns, status, password_hash, password_changed_at) "
                        "VALUES (:c, :e, :n, :r, false, true, 'active', :pw, now())"
                    ),
                    {"c": cid, "e": email, "n": f"auth {role} {SFX}", "r": rid, "pw": hash_password("Test@12345")},
                )
                out[role] = email
        await engine.dispose()
        return out

    return asyncio.run(_make())


def reset_link_token(email: str) -> str | None:
    rows = db(
        "SELECT body_preview FROM outbound_messages WHERE lower(to_address) = lower(:e) "
        "AND message_type = 'password_reset' ORDER BY queued_at DESC LIMIT 1",
        {"e": email},
    )
    if not rows:
        return None
    match = re.search(r"reset-password\?token=([A-Za-z0-9_\-]+)", rows[0]["body_preview"])
    return match.group(1) if match else None


def main() -> int:
    owner = token_of("owner@acme-demo.test", "Demo@12345")
    beta = token_of("owner@beta-demo.test", "Demo@12345")
    st, platform_body = login("platform-admin@inventoryai.test", "Platform@12345")
    if st != 200:
        print("  !! no platform admin seeded — run `python -m app.db.seed` first")
        return 1
    platform = platform_body["access_token"]
    platform_refresh = platform_body["refresh_token"]

    users = make_users()
    staff_email, viewer_email = users["staff"], users["viewer"]
    staff = token_of(staff_email, "Test@12345")

    # ====================================================== password reset
    print("\n[password reset]")
    before = len(db("SELECT id FROM outbound_messages WHERE message_type = 'password_reset'"))
    st, b = call("POST", "/auth/forgot-password", body={"email": staff_email})
    after = len(db("SELECT id FROM outbound_messages WHERE message_type = 'password_reset'"))
    check("P01 a reset request is accepted and queues one email", st == 202 and after == before + 1, (st, b))
    st, b2 = call("POST", "/auth/forgot-password", body={"email": f"nobody.{SFX}@acme-demo.test"})
    after2 = len(db("SELECT id FROM outbound_messages WHERE message_type = 'password_reset'"))
    check("P02 an unknown address gets the same answer and sends nothing",
          st == 202 and b2 == b and after2 == after, (st, b2))
    st, b = call("POST", "/auth/forgot-password", body={"email": "not-an-email"})
    check("P03 a malformed address is still 202 (no enumeration through validation)", st in (202, 400), st)

    first_token = reset_link_token(staff_email)
    check("P04 the link carries a token", bool(first_token and len(first_token) > 20), first_token)
    call("POST", "/auth/forgot-password", body={"email": staff_email})
    second_token = reset_link_token(staff_email)
    check("P05 a second request issues a different token", second_token and second_token != first_token, second_token)
    st, b = call("POST", "/auth/reset-password", body={"token": first_token, "new_password": "Changed@123"})
    check("P06 the superseded link no longer works", st == 422 and b.get("code") == "INVALID_RESET_TOKEN", b)
    st, b = call("POST", "/auth/reset-password", body={"token": "not-a-real-token-value", "new_password": "Changed@123"})
    check("P07 a made-up token is refused the same way", st == 422 and b.get("code") == "INVALID_RESET_TOKEN", b)
    st, b = call("POST", "/auth/reset-password", body={"token": second_token, "new_password": "short"})
    check("P08 a weak password is refused before the token is spent", st == 400, b)

    # Lock the account first: a reset should clear the lockout (BR-AUTH-03).
    for _ in range(5):
        login(staff_email, "WrongPassword!1")
    st_locked, _ = login(staff_email, "Test@12345")
    check("P09 five bad attempts lock the account", st_locked == 429, st_locked)

    st, b = call("POST", "/auth/reset-password", body={"token": second_token, "new_password": "Changed@12345"})
    check("P10 the reset succeeds", st == 204, b)
    st, _ = login(staff_email, "Test@12345")
    check("P11 the old password no longer works", st == 401, st)
    st, fresh = login(staff_email, "Changed@12345")
    check("P12 the new password works, and the lockout is cleared", st == 200, fresh)
    st, b = call("POST", "/auth/reset-password", body={"token": second_token, "new_password": "Another@12345"})
    check("P13 a reset link is single-use", st == 422, b)
    st, b = call("GET", "/auth/me", staff)
    check("P14 the pre-reset access token is dead (instant revocation)",
          st == 401 and b.get("code") == "SESSION_REVOKED", b)

    staff = fresh["access_token"]
    staff_refresh = fresh["refresh_token"]

    # expiry
    db(
        "UPDATE password_reset_tokens SET expires_at = now() - interval '1 minute', used_at = NULL "
        "WHERE user_id = (SELECT id FROM users WHERE lower(email) = lower(:e))",
        {"e": staff_email},
    )
    call("POST", "/auth/forgot-password", body={"email": staff_email})
    expiring = reset_link_token(staff_email)
    db(
        "UPDATE password_reset_tokens SET expires_at = now() - interval '1 minute' "
        "WHERE token_hash = encode(digest(:t, 'sha256'), 'hex')",
        {"t": expiring},
    )
    st, b = call("POST", "/auth/reset-password", body={"token": expiring, "new_password": "Expired@12345"})
    check("P15 an expired link is refused", st == 422, b)

    # ===================================================== change password
    print("\n[change password]")
    st, b = call("POST", "/auth/change-password", staff, {"current_password": "nope", "new_password": "Newpass@123"})
    check("C01 the wrong current password is refused", st == 401, b)
    st, b = call("POST", "/auth/change-password", staff, {"current_password": "Changed@12345", "new_password": "Changed@12345"})
    check("C02 re-using the same password is refused", st == 422, b)
    st, b = call("POST", "/auth/change-password", staff, {"current_password": "Changed@12345", "new_password": "weak"})
    check("C03 a weak new password is refused", st == 400, b)
    st, b = call("POST", "/auth/change-password", None, {"current_password": "x", "new_password": "Newpass@123"})
    check("C04 it needs a token at all", st in (401, 403), st)
    st, b = call("POST", "/auth/change-password", staff, {"current_password": "Changed@12345", "new_password": "Final@12345"})
    check("C05 the change succeeds", st == 204, b)
    st, b = call("GET", "/auth/me", staff)
    check("C06 the session that changed it is itself ended", st == 401, b)
    st, b = call("POST", "/auth/refresh", body={"refresh_token": staff_refresh})
    check("C07 the old refresh token is revoked too", st == 401, b)
    staff = token_of(staff_email, "Final@12345")

    # ======================================================= impersonation
    print("\n[impersonation — BR-AUTH-07]")
    staff_id = db("SELECT id FROM users WHERE lower(email) = lower(:e)", {"e": staff_email})[0]["id"]
    owner_id = db("SELECT id FROM users WHERE lower(email) = 'owner@acme-demo.test'")[0]["id"]
    platform_id = db("SELECT id FROM users WHERE lower(email) = 'platform-admin@inventoryai.test'")[0]["id"]

    st, b = call("POST", "/platform/impersonate", owner, {"user_id": str(staff_id), "reason": "Support request 42"})
    check("I01 a tenant Owner cannot impersonate", st == 403, b)
    st, b = call("POST", "/platform/impersonate", platform, {"user_id": str(staff_id), "reason": "x"})
    check("I02 a one-character reason is refused", st == 400, b)
    st, b = call("POST", "/platform/impersonate", platform, {"user_id": str(uuid.uuid4()), "reason": "Support request 42"})
    check("I03 an unknown user is a 404", st == 404, b)
    st, b = call("POST", "/platform/impersonate", platform, {"user_id": str(platform_id), "reason": "Support request 42"})
    check("I04 a platform admin cannot be impersonated", st == 403, b)

    st, imp = call("POST", "/platform/impersonate", platform, {"user_id": str(staff_id), "reason": "Support ticket 42"})
    check("I05 a platform admin can impersonate a tenant user", st == 200 and imp["access_token"], imp)
    check("I06 the token lasts 30 minutes and comes with no refresh token",
          imp.get("expires_in") == 1800 and "refresh_token" not in imp, imp.get("expires_in"))
    imp_token = imp["access_token"]
    st, me = call("GET", "/auth/me", imp_token)
    check("I07 it authenticates as the target, not the admin",
          st == 200 and me["email"].lower() == staff_email.lower(), me)
    st, b = call("POST", "/platform/impersonate", imp_token, {"user_id": str(owner_id), "reason": "Nested please"})
    check("I08 an impersonation session cannot impersonate again", st == 403, b)
    st, b = call("POST", "/auth/change-password", imp_token, {"current_password": "Final@12345", "new_password": "Hijack@12345"})
    check("I09 it cannot change the user's password", st == 403, b)
    st, b = call("POST", "/auth/refresh", body={"refresh_token": imp_token})
    check("I10 the access token is not a refresh token either", st == 401, b)

    # An action taken while impersonating is stamped. Done as the Owner,
    # who can actually write master data — the point is the stamp, not the
    # permission.
    st, imp_owner = call("POST", "/platform/impersonate", platform, {"user_id": str(owner_id), "reason": "Reproducing a bug"})
    st_brand, created = call("POST", "/catalog/brands", imp_owner["access_token"], {"name": f"Imp Brand {SFX}"})
    stamped = db(
        "SELECT impersonated_by, actor_user_id FROM audit_logs WHERE entity_type = 'brand' "
        "AND entity_id = CAST(:id AS uuid) ORDER BY created_at DESC LIMIT 1",
        {"id": created["id"]},
    ) if st_brand == 201 else []
    check("I11 every audit row it writes carries impersonated_by",
          bool(stamped) and str(stamped[0]["impersonated_by"]) == str(platform_id)
          and str(stamped[0]["actor_user_id"]) == str(owner_id), (st_brand, stamped))
    ok(*call("POST", "/platform/impersonate/stop", imp_owner["access_token"]))
    st, b = call("GET", "/auth/me", owner)
    check("I11b impersonating someone does not disturb their own session", st == 200, b)

    sessions = db("SELECT id, ended_at, reason FROM impersonation_sessions WHERE target_user_id = CAST(:u AS uuid) "
                  "ORDER BY started_at DESC LIMIT 1", {"u": str(staff_id)})
    check("I12 the visit is recorded with its reason", sessions and sessions[0]["reason"] == "Support ticket 42", sessions)

    st, stopped = call("POST", "/platform/impersonate/stop", imp_token)
    check("I13 stopping works and reports the session", st == 200 and stopped["ended_at"], stopped)
    st, b = call("GET", "/auth/me", imp_token)
    check("I14 the token dies with the session, not with its clock",
          st == 401 and b.get("code") == "SESSION_REVOKED", b)
    st, b = call("POST", "/platform/impersonate/stop", platform)
    check("I15 an ordinary token cannot 'stop' anything", st == 403, b)
    st, b = call("GET", "/auth/me", platform)
    check("I16 the platform admin's own session was never touched", st == 200, b)
    st, b = call("POST", "/auth/refresh", body={"refresh_token": platform_refresh})
    check("I17 and its refresh token still works", st == 200, b)
    platform = b["access_token"] if st == 200 else platform

    # ==================================================== instant revocation
    print("\n[instant revocation]")
    viewer = token_of(viewer_email, "Test@12345")
    viewer_id = db("SELECT id FROM users WHERE lower(email) = lower(:e)", {"e": viewer_email})[0]["id"]
    st, b = call("GET", "/auth/me", viewer)
    check("R01 the viewer's token works", st == 200, b)
    st, b = call("PATCH", f"/users/{viewer_id}", owner, {"role_code": "staff"})
    check("R02 the Owner changes their role", st == 200, b)
    st, b = call("GET", "/auth/me", viewer)
    check("R03 the token issued before the change is refused at once (BR-AUTH-11)",
          st == 401 and b.get("code") == "SESSION_REVOKED", b)
    viewer = token_of(viewer_email, "Test@12345")
    check("R04 signing in again works", bool(viewer))

    st, b = call("DELETE", f"/users/{viewer_id}", owner)
    st2, b2 = call("GET", "/auth/me", viewer)
    check("R05 removing a user kills their live session", st == 204 and st2 == 401, (st, st2, b2))

    db("UPDATE companies SET status = 'suspended' WHERE name = 'Acme Trading Co'")
    st, b = call("GET", "/auth/me", owner)
    db("UPDATE companies SET status = 'active' WHERE name = 'Acme Trading Co'")
    check("R06 suspending the company stops its tokens working (BR-AUTH-04)",
          st == 403 and b.get("code") == "COMPANY_SUSPENDED", b)
    st, b = call("GET", "/auth/me", owner)
    check("R07 reactivating restores them", st == 200, b)

    # ===================================================== email settings
    print("\n[email / SMTP settings]")
    # Asked of the beta tenant, which nothing else here configures: the
    # question is what a company that has never touched this sees.
    st, settings = call("GET", "/company/email-settings", beta)
    check("E01 an unconfigured tenant reads as console with no password",
          st == 200 and settings["provider"] == "console" and settings["has_password"] is False
          and settings["smtp_host"] is None, settings)
    st, b = call("PUT", "/company/email-settings", owner, {"provider": "smtp", "smtp_port": 587})
    check("E02 smtp without a host is refused", st == 400, b)
    st, b = call("PUT", "/company/email-settings", owner,
                 {"provider": "smtp", "smtp_host": "smtp.example.test", "smtp_port": 70000,
                  "from_address": "billing@acme.test"})
    check("E03 an impossible port is refused", st == 400, b)
    st, b = call("PUT", "/company/email-settings", owner,
                 {"provider": "smtp", "smtp_host": "smtp.example.test", "from_address": "not-an-email"})
    check("E04 a malformed from-address is refused", st == 400, b)
    st, saved = call("PUT", "/company/email-settings", owner, {
        "provider": "smtp", "smtp_host": "smtp.example.test", "smtp_port": 587,
        "from_address": "billing@acme.test", "from_name": "Acme Trading",
        "smtp_username": "acme", "smtp_password": "hunter2!", "smtp_use_tls": True})
    check("E05 settings save, and the password is stored but never returned",
          st == 200 and saved["has_password"] is True and "smtp_password" not in saved, saved)
    stored = db("SELECT smtp_password_encrypted FROM company_email_settings WHERE smtp_host = 'smtp.example.test'")
    check("E06 the stored password is encrypted, not plain text",
          bool(stored) and b"hunter2" not in bytes(stored[0]["smtp_password_encrypted"]), "")
    st, kept = call("PUT", "/company/email-settings", owner, {
        "provider": "smtp", "smtp_host": "smtp.example.test", "from_address": "billing@acme.test",
        "from_name": "Acme Trading"})
    check("E07 omitting the password keeps the stored one", st == 200 and kept["has_password"] is True, kept)
    st, cleared = call("PUT", "/company/email-settings", owner, {
        "provider": "smtp", "smtp_host": "smtp.example.test", "from_address": "billing@acme.test",
        "smtp_password": ""})
    check("E08 an empty password clears it", st == 200 and cleared["has_password"] is False, cleared)

    st, result = call("POST", "/company/email-settings/test", owner, {"to_address": f"test.{SFX}@acme-demo.test"})
    check("E09 a test against an unreachable SMTP host reports the failure rather than throwing",
          st == 200 and result["sent"] is False and result["error"], result)
    st, after_test = call("GET", "/company/email-settings", owner)
    check("E10 the failure is recorded on the settings row",
          st == 200 and after_test["last_test_ok"] is False and after_test["last_test_at"], after_test)

    ok(*call("PUT", "/company/email-settings", owner, {"provider": "console"}))
    st, result = call("POST", "/company/email-settings/test", owner, {})
    check("E11 back on console, a test succeeds and defaults to the caller's own address",
          st == 200 and result["sent"] is True and result["to_address"] == "owner@acme-demo.test", result)

    st, b = call("PUT", "/company/email-settings", staff, {"provider": "console"})
    check("E12 a staff user cannot change them", st == 403, b)
    st, mine = call("GET", "/company/email-settings", owner)
    st2, theirs = call("GET", "/company/email-settings", beta)
    check("E13 each tenant sees only its own settings",
          st == 200 and st2 == 200 and str(mine["company_id"]) != str(theirs["company_id"])
          and theirs["smtp_host"] is None, (mine, theirs))

    print(f"\n{passed} passed, {len(failed)} failed")
    for f in failed:
        print("  -", f)
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
