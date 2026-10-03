"""Move InventoryAI's passwords and keys into Secrets Manager (Floci locally).

Run from the backend folder, with Floci running:

    python -m scripts.secrets_manager push        # 1. copy .env secrets into Secrets Manager
    python -m scripts.secrets_manager verify      # 2. read them back, check the API can start
    #    restart Floci once, run verify again      #    (proves the secret survives a restart)
    python -m scripts.secrets_manager strip-env   # 3. blank the values in .env
    python -m scripts.secrets_manager show        # key names and lengths, never values
    python -m scripts.secrets_manager reveal JWT_SECRET   # print one value (recovery)

What `push` does, in order:

1. Reads `backend/.env` and the existing secret (if any). A value already
   in Secrets Manager is kept unless `.env` has a non-empty value for it.
2. Generates a strong JWT_SECRET and a separate SECRETS_KEY when the current
   ones are blank, the public development default, or shorter than 32
   characters (security audit H5). Changing JWT_SECRET signs everybody out
   once; that is expected.
3. If SECRETS_KEY changes, re-encrypts every stored company SMTP password
   from the old key to the new one, inside a database transaction.
4. Writes the secret, reads it back and compares, and only then commits the
   database transaction. If anything fails, the database is rolled back and
   the previous secret version is put back, so the two never disagree.

Nothing here prints a secret value except `reveal`, on request.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets as pysecrets
import sys
from pathlib import Path

from dotenv import dotenv_values

from app.core import secrets_manager as sm
from app.core.config import DEV_JWT_SECRET, MIN_SECRET_LENGTH, Settings

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
DEFAULT_SECRET_ID = "inventoryai/backend"


def _bootstrap(secret_id: str | None) -> Settings:
    """Settings straight from `.env`, without the Secrets Manager overlay —
    which is what tells us how to reach Secrets Manager in the first place."""
    s = Settings()
    if secret_id:
        s = s.model_copy(update={"secrets_manager_secret_id": secret_id})
    elif not s.secrets_manager_secret_id:
        s = s.model_copy(update={"secrets_manager_secret_id": DEFAULT_SECRET_ID})
    return s


def _weak(value: str) -> bool:
    return not value or value == DEV_JWT_SECRET or len(value) < MIN_SECRET_LENGTH


def _new_secret() -> str:
    return pysecrets.token_urlsafe(48)  # 64 URL-safe characters


def _existing(settings: Settings) -> tuple[dict, bool]:
    client = sm.client(settings)
    try:
        raw = client.get_secret_value(SecretId=settings.secrets_manager_secret_id)["SecretString"]
        return json.loads(raw), True
    except client.exceptions.ResourceNotFoundException:
        return {}, False


def _write(settings: Settings, data: dict, exists: bool) -> None:
    client = sm.client(settings)
    body = json.dumps(data, sort_keys=True)
    if exists:
        client.put_secret_value(SecretId=settings.secrets_manager_secret_id, SecretString=body)
    else:
        client.create_secret(
            Name=settings.secrets_manager_secret_id,
            Description="InventoryAI backend: database URLs, JWT_SECRET, SECRETS_KEY, SMTP and AI keys",
            SecretString=body,
        )


async def _reencrypt(platform_url: str, old_key: str, new_key: str, commit_after) -> int:
    """Re-encrypt company SMTP passwords old_key -> new_key, then run
    `commit_after()` (writes the secret) before committing. Returns rows."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(platform_url)
    try:
        async with engine.connect() as conn:
            trans = await conn.begin()
            try:
                result = await conn.execute(
                    text(
                        "UPDATE company_email_settings "
                        "SET smtp_password_encrypted = pgp_sym_encrypt(pgp_sym_decrypt(smtp_password_encrypted, :old), :new) "
                        "WHERE smtp_password_encrypted IS NOT NULL"
                    ),
                    {"old": old_key, "new": new_key},
                )
                rows = result.rowcount or 0
                commit_after()
                await trans.commit()
                return rows
            except Exception:
                await trans.rollback()
                raise
    finally:
        await engine.dispose()


# ------------------------------------------------------------------ commands


def cmd_push(args) -> int:
    settings = _bootstrap(args.secret_id)
    env = {k: (v or "") for k, v in dotenv_values(ENV_PATH).items()}
    current, exists = _existing(settings)
    previous = dict(current)

    data = dict(current)
    for key in sm.SECRET_ENV_KEYS:
        value = env.get(key, "").strip()
        if value:
            data[key] = value
        data.setdefault(key, "")

    # The key that encrypted SMTP passwords until now: what the running
    # code would have used (email.secrets_key(): SECRETS_KEY or JWT_SECRET,
    # and a blank JWT_SECRET meant the development default).
    old_jwt = data["JWT_SECRET"] or DEV_JWT_SECRET
    old_secrets_key = data["SECRETS_KEY"] or old_jwt

    changes = []
    if _weak(data["JWT_SECRET"]):
        data["JWT_SECRET"] = _new_secret()
        changes.append("JWT_SECRET generated (everyone will need to sign in again once)")
    if _weak(data["SECRETS_KEY"]) or data["SECRETS_KEY"] == data["JWT_SECRET"]:
        data["SECRETS_KEY"] = _new_secret()
        changes.append("SECRETS_KEY generated")

    missing = [k for k in sm.REQUIRED_SECRET_KEYS if not data.get(k)]
    if missing:
        print(f"Cannot push: no value for {', '.join(missing)} in .env or the existing secret.")
        return 1

    print(f"Secret      : {settings.secrets_manager_secret_id} ({'update' if exists else 'create'})")
    print(f"Endpoint    : {settings.secrets_manager_endpoint_url or settings.aws_endpoint_url or 'AWS'}")
    for key in sm.SECRET_ENV_KEYS:
        state = "set" if data.get(key) else "empty"
        print(f"  {key:<24} {state}")
    for c in changes:
        print(f"  * {c}")
    if args.dry_run:
        print("\nDry run: nothing written.")
        return 0

    def write_and_check() -> None:
        _write(settings, data, exists)
        back, _ = _existing(settings)
        if any(back.get(k) != data.get(k) for k in data):
            raise RuntimeError("The secret read back does not match what was written.")

    try:
        if data["SECRETS_KEY"] != old_secrets_key:
            rows = asyncio.run(_reencrypt(data["PLATFORM_DATABASE_URL"], old_secrets_key, data["SECRETS_KEY"], write_and_check))
            print(f"  * re-encrypted {rows} stored company SMTP password(s) with the new SECRETS_KEY")
        else:
            write_and_check()
    except Exception as exc:  # noqa: BLE001
        print(f"\nFAILED: {type(exc).__name__}: {str(exc)[:300]}")
        try:
            if exists:
                _write(settings, previous, True)
                print("The previous secret version was put back. The database was not changed.")
            else:
                print("No secret was kept. The database was not changed.")
        except Exception:  # noqa: BLE001
            print("Could not restore the previous secret version - check it with `show`.")
        return 1

    if not env.get("SECRETS_MANAGER_SECRET_ID"):
        with ENV_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                "\n# Passwords and keys are read from this Secrets Manager secret at startup.\n"
                f"SECRETS_MANAGER_SECRET_ID={settings.secrets_manager_secret_id}\n"
            )
        print(f"  * added SECRETS_MANAGER_SECRET_ID={settings.secrets_manager_secret_id} to backend/.env")
    print("\nDone. Next:")
    print("  1. python -m scripts.secrets_manager verify")
    print("  2. restart Floci, run verify again (proves the secret survives a restart)")
    print("  3. python -m scripts.secrets_manager strip-env")
    return 0


def _strength_problems(data: dict) -> list[str]:
    out = []
    if _weak(data.get("JWT_SECRET", "")):
        out.append("JWT_SECRET is blank, the development default, or too short")
    if _weak(data.get("SECRETS_KEY", "")) or data.get("SECRETS_KEY") == data.get("JWT_SECRET"):
        out.append("SECRETS_KEY is weak or equal to JWT_SECRET")
    return out


def cmd_verify(args) -> int:
    settings = _bootstrap(args.secret_id)
    ok = True
    try:
        data = sm.fetch_raw(settings)
        print(f"ok    secret '{settings.secrets_manager_secret_id}' is readable")
    except sm.SecretsUnavailableError as exc:
        print(f"FAIL  {exc}")
        return 1

    for key in sm.REQUIRED_SECRET_KEYS:
        if not str(data.get(key, "")).strip():
            ok = False
            print(f"FAIL  {key} is missing or empty in the secret")
    for p in _strength_problems(data):
        ok = False
        print(f"FAIL  {p}")
    if ok:
        print("ok    required keys present, JWT_SECRET and SECRETS_KEY strong and distinct")

    env = {k: (v or "") for k, v in dotenv_values(ENV_PATH).items()}
    if not env.get("SECRETS_MANAGER_SECRET_ID"):
        ok = False
        print("FAIL  SECRETS_MANAGER_SECRET_ID is not set in backend/.env, so the API will not read the secret")
    left = [k for k in sm.SECRET_ENV_KEYS if env.get(k, "").strip()]
    if left:
        print(f"warn  still in .env as plain text: {', '.join(left)}  (run strip-env once verify passes)")
    else:
        print("ok    no secret values left in backend/.env")

    # What the API itself will load.
    from app.core import config

    config.get_settings.cache_clear()
    try:
        loaded = config.get_settings()
        problems = loaded.production_problems()
        if loaded.jwt_secret != data.get("JWT_SECRET"):
            ok = False
            print("FAIL  the API would not take JWT_SECRET from Secrets Manager")
        elif problems:
            ok = False
            print("FAIL  the API would refuse to start: " + " | ".join(problems))
        else:
            print("ok    the API's settings load from Secrets Manager and pass the startup checks")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL  loading settings: {type(exc).__name__}: {str(exc)[:200]}")

    if not args.skip_db:
        ok = asyncio.run(_check_db(data)) and ok
    print("\nAll checks passed." if ok else "\nSome checks failed.")
    return 0 if ok else 1


async def _check_db(data: dict) -> bool:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    ok = True
    for key in ("DATABASE_URL", "APP_DATABASE_URL", "PLATFORM_DATABASE_URL"):
        engine = create_async_engine(data[key])
        try:
            async with engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            print(f"ok    {key} connects")
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"FAIL  {key} does not connect: {type(exc).__name__}")
        finally:
            await engine.dispose()
    try:
        engine = create_async_engine(data["PLATFORM_DATABASE_URL"])
        async with engine.connect() as conn:
            bad = (
                await conn.execute(
                    text(
                        # pgp_sym_decrypt raises on a wrong key, so this
                        # either counts 0 bad rows or lands in `except`.
                        "SELECT COUNT(*) FILTER (WHERE pgp_sym_decrypt(smtp_password_encrypted, :k) IS NULL) "
                        "FROM company_email_settings WHERE smtp_password_encrypted IS NOT NULL"
                    ),
                    {"k": data["SECRETS_KEY"]},
                )
            ).scalar_one()
        print("ok    stored SMTP passwords decrypt with SECRETS_KEY" if not bad else f"FAIL  {bad} SMTP password(s) do not decrypt")
        ok = ok and not bad
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"FAIL  stored SMTP passwords do not decrypt with SECRETS_KEY ({type(exc).__name__})")
    finally:
        await engine.dispose()
    return ok


def cmd_strip_env(args) -> int:
    settings = _bootstrap(args.secret_id)
    try:
        data = sm.fetch_raw(settings)
    except sm.SecretsUnavailableError as exc:
        print(f"Not stripping: {exc}")
        return 1
    missing = [k for k in sm.REQUIRED_SECRET_KEYS if not str(data.get(k, "")).strip()]
    if missing or _strength_problems(data):
        print("Not stripping: the secret is incomplete or weak. Run push and verify first.")
        return 1
    env = {k: (v or "") for k, v in dotenv_values(ENV_PATH).items()}
    for key in sm.SECRET_ENV_KEYS:
        value = env.get(key, "").strip()
        if value and data.get(key) != value:
            print(f"Not stripping: {key} in .env differs from the secret. Run push first so nothing is lost.")
            return 1
    if not args.yes:
        answer = input(f"Blank {', '.join(sm.SECRET_ENV_KEYS)} in {ENV_PATH}? [y/N] ").strip().lower()
        if answer != "y":
            print("Nothing changed.")
            return 1

    lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    out, seen_id = [], False
    for line in lines:
        stripped = line.lstrip()
        name = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if name in sm.SECRET_ENV_KEYS:
            out.append(f"{name}=")
            continue
        if name == "SECRETS_MANAGER_SECRET_ID":
            seen_id = True
        out.append(line)
    header = [
        "# ---------------------------------------------------------------- Secrets",
        f"# Passwords and keys live in Secrets Manager ({settings.secrets_manager_secret_id}),",
        "# not in this file. The API reads them at startup and refuses to start",
        "# if it cannot. Manage them with:  python -m scripts.secrets_manager --help",
    ]
    if not seen_id:
        header.append(f"SECRETS_MANAGER_SECRET_ID={settings.secrets_manager_secret_id}")
    ENV_PATH.write_text("\n".join(header + [""] + out) + "\n", encoding="utf-8")
    print(f"Blanked {len(sm.SECRET_ENV_KEYS)} keys in {ENV_PATH}. The values are only in Secrets Manager now.")
    return 0


def cmd_show(args) -> int:
    settings = _bootstrap(args.secret_id)
    data = sm.fetch_raw(settings)
    client = sm.client(settings)
    meta = client.describe_secret(SecretId=settings.secrets_manager_secret_id)
    print(f"{settings.secrets_manager_secret_id}  (last changed {meta.get('LastChangedDate', 'n/a')})")
    for key in sorted(data):
        print(f"  {key:<24} {len(str(data[key])):>3} chars")
    return 0


def cmd_reveal(args) -> int:
    settings = _bootstrap(args.secret_id)
    data = sm.fetch_raw(settings)
    if args.key not in data:
        print(f"{args.key} is not in the secret.")
        return 1
    print(data[args.key])
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m scripts.secrets_manager", description=__doc__.split("\n\n")[0])
    parser.add_argument("--secret-id", default=None, help=f"default: SECRETS_MANAGER_SECRET_ID or {DEFAULT_SECRET_ID}")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("push", help="copy .env secrets into Secrets Manager (generates weak keys)")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_push)
    p = sub.add_parser("verify", help="check the secret, the API settings and the database logins")
    p.add_argument("--skip-db", action="store_true")
    p.set_defaults(func=cmd_verify)
    p = sub.add_parser("strip-env", help="blank the secret values in backend/.env")
    p.add_argument("--yes", action="store_true")
    p.set_defaults(func=cmd_strip_env)
    sub.add_parser("show", help="list keys and lengths").set_defaults(func=cmd_show)
    p = sub.add_parser("reveal", help="print one value")
    p.add_argument("key")
    p.set_defaults(func=cmd_reveal)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
