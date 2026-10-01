"""A separate database, API and frontend for the automated suites.

The suites create records with random suffixes, sign people out, suspend
companies and change settings. Run against the everyday database they bury
real data under test companies, so `run_all.py --isolated` runs them here
instead:

  * database `inventoryai_test` (same server and roles as backend/.env),
    migrated to head and seeded with the demo tenants the suites sign in as
    (owner@acme-demo.test, owner@beta-demo.test, platform-admin@inventoryai.test);
  * bucket `inventoryai-test-documents` on the same S3 stand-in;
  * API on :8010 and frontend on :3010 (its own `.next-test` build folder),
    both stopped again when the run ends.

    python tests/test_stack.py reset   # drop and rebuild the test database
    python tests/test_stack.py up      # start API + frontend and wait (Ctrl+C stops)

Your everyday database, API (:8000) and frontend (:3000) are never touched.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
PYTHON = str(BACKEND / ".venv" / "Scripts" / "python.exe") if os.name == "nt" else str(BACKEND / ".venv" / "bin" / "python")

TEST_DB = "inventoryai_test"
TEST_BUCKET = "inventoryai-test-documents"
API_PORT, APP_PORT = 8010, 3010
API_URL, APP_URL = f"http://127.0.0.1:{API_PORT}", f"http://localhost:{APP_PORT}"


def _dotenv() -> dict[str, str]:
    values: dict[str, str] = {}
    for line in (BACKEND / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _with_db(url: str, db: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/" + db, parts.query, parts.fragment))


def settings_env() -> dict[str, str]:
    """Environment overrides that point the app and every suite at the test stack."""
    env = _dotenv()
    owner = _with_db(env["DATABASE_URL"], TEST_DB)
    app = _with_db(env["APP_DATABASE_URL"], TEST_DB)
    platform = _with_db(env["PLATFORM_DATABASE_URL"], TEST_DB)
    plain = lambda u: u.replace("+asyncpg", "")
    return {
        "DATABASE_URL": owner,
        "APP_DATABASE_URL": app,
        "PLATFORM_DATABASE_URL": platform,
        "S3_BUCKET": TEST_BUCKET,
        "APP_BASE_URL": APP_URL,
        "CORS_ALLOWED_ORIGINS": f"{APP_URL},http://127.0.0.1:{APP_PORT}",
        # The suites fail sign-ins on purpose; limits would turn that into 429s.
        "RATE_LIMIT_ENABLED": "false",
        "API_URL": API_URL,
        "APP_URL": APP_URL,
        "TEST_PLATFORM_DATABASE_URL": plain(platform),
        "TEST_DATABASE_URL": plain(owner),
        "PYTHONIOENCODING": "utf-8",
    }


def _sql(url: str, statements: list[str]) -> None:
    import asyncio

    import asyncpg

    async def run():
        conn = await asyncpg.connect(url.replace("+asyncpg", ""))
        try:
            for statement in statements:
                await conn.execute(statement)
        finally:
            await conn.close()

    asyncio.run(run())


def _exists(url: str) -> bool:
    import asyncio

    import asyncpg

    async def run():
        conn = await asyncpg.connect(_with_db(url, "postgres").replace("+asyncpg", ""))
        try:
            return bool(await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB))
        finally:
            await conn.close()

    return asyncio.run(run())


def prepare(reset: bool = False) -> None:
    """Create (or rebuild) the test database, migrate it, seed the demo tenants."""
    base = _dotenv()
    owner_url = base["DATABASE_URL"]
    owner_role = urlsplit(owner_url).username
    app_role = urlsplit(base["APP_DATABASE_URL"]).username
    platform_role = urlsplit(base["PLATFORM_DATABASE_URL"]).username
    admin = _with_db(owner_url, "postgres")

    if reset and _exists(owner_url):
        print(f"Dropping {TEST_DB} ...")
        _sql(admin, [f"DROP DATABASE {TEST_DB} WITH (FORCE)"])
    fresh = not _exists(owner_url)
    if fresh:
        print(f"Creating {TEST_DB} ...")
        _sql(admin, [f"CREATE DATABASE {TEST_DB} OWNER {owner_role}"])
        # Same grants BACKEND-SETUP.md gives the everyday database; default
        # privileges are per database, so they are repeated here.
        _sql(_with_db(owner_url, TEST_DB), [
            # The migrations expect these (BACKEND-SETUP.md, Prerequisites).
            "CREATE EXTENSION IF NOT EXISTS pgcrypto",
            "CREATE EXTENSION IF NOT EXISTS pg_trgm",
            "CREATE EXTENSION IF NOT EXISTS vector",
            f"GRANT CONNECT ON DATABASE {TEST_DB} TO {app_role}, {platform_role}",
            f"GRANT USAGE ON SCHEMA public TO {app_role}, {platform_role}",
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {app_role}, {platform_role}",
            f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner_role} IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {app_role}, {platform_role}",
        ])

    env = dict(os.environ, **settings_env())
    print("Migrating the test database ...")
    subprocess.run([PYTHON, "-m", "alembic", "upgrade", "head"], cwd=BACKEND, env=env, check=True,
                   stdout=subprocess.DEVNULL)
    subprocess.run([PYTHON, "-m", "app.db.seed", "--demo"], cwd=BACKEND, env=env, check=True)
    _bucket(base)


def _bucket(base: dict[str, str]) -> None:
    import boto3

    s3 = boto3.client("s3", endpoint_url=base.get("AWS_ENDPOINT_URL") or None,
                      aws_access_key_id=base.get("AWS_ACCESS_KEY_ID"),
                      aws_secret_access_key=base.get("AWS_SECRET_ACCESS_KEY"),
                      region_name=base.get("AWS_REGION", "us-east-1"))
    try:
        s3.head_bucket(Bucket=TEST_BUCKET)
    except Exception:
        s3.create_bucket(Bucket=TEST_BUCKET)
        print(f"Created bucket {TEST_BUCKET}.")
    # Same lock-down as the real bucket (start-storage.ps1); verify_s3 checks it.
    s3.put_public_access_block(Bucket=TEST_BUCKET, PublicAccessBlockConfiguration=dict(
        BlockPublicAcls=True, IgnorePublicAcls=True, BlockPublicPolicy=True, RestrictPublicBuckets=True))


def _reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def _wait(url: str, what: str, seconds: int) -> None:
    deadline = time.monotonic() + seconds
    while not _reachable(url):
        if time.monotonic() > deadline:
            raise RuntimeError(f"The test {what} did not start at {url} within {seconds}s.")
        time.sleep(1)


class Stack:
    """Starts the test API and (optionally) frontend; `stop()` ends both."""

    def __init__(self, frontend: bool) -> None:
        self.frontend = frontend
        self.procs: list[subprocess.Popen] = []
        self.log_dir = ROOT / "tests" / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _spawn(self, args: list[str], cwd: Path, env: dict, log: str) -> None:
        out = open(self.log_dir / log, "w", encoding="utf-8")
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.procs.append(subprocess.Popen(args, cwd=cwd, env=env, stdout=out, stderr=subprocess.STDOUT,
                                           creationflags=flags, shell=False))

    def start(self) -> None:
        for port in (API_PORT,) + ((APP_PORT,) if self.frontend else ()):
            if _reachable(f"http://127.0.0.1:{port}/"):
                raise RuntimeError(f"Port {port} is already in use; stop whatever is running there first.")
        env = dict(os.environ, **settings_env())
        self._spawn([PYTHON, "-m", "uvicorn", "app.main:app", "--port", str(API_PORT)], BACKEND, env, "test-api.log")
        _wait(API_URL + "/health", "API", 60)
        print(f"Test API running at {API_URL}")
        if self.frontend:
            app_env = dict(os.environ, NEXT_PUBLIC_API_BASE_URL=API_URL, NEXT_DIST_DIR=".next-test")
            npx = "npx.cmd" if os.name == "nt" else "npx"
            self._spawn([npx, "next", "dev", "-p", str(APP_PORT)], FRONTEND, app_env, "test-frontend.log")
            _wait(APP_URL + "/login", "frontend", 180)
            print(f"Test frontend running at {APP_URL}")

    def stop(self) -> None:
        for proc in reversed(self.procs):
            if proc.poll() is None:
                if os.name == "nt":
                    # The frontend is npx -> node; only a tree kill reaches the server.
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
                else:
                    proc.terminate()
        self.procs.clear()


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "reset":
        prepare(reset=True)
        return 0
    if action == "up":
        prepare()
        stack = Stack(frontend=True)
        try:
            stack.start()
            print("Press Ctrl+C to stop.")
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            stack.stop()
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
