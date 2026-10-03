"""Checks the startup secrets guard (security audit H5), the Secrets Manager
loading, and the request rate limiter.

Needs no running server or database:

    cd backend
    python -m scripts.verify_security_config
"""
from __future__ import annotations

import sys

from starlette.requests import Request

from app.core import rate_limit
from app.core.config import DEV_JWT_SECRET, Settings, get_settings
from app.core.errors import ApiError
from app.core.rate_limit import Rule, SlidingWindowLimiter

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


def settings(**values) -> Settings:
    # _env_file=None: judge exactly what is passed, not this machine's .env.
    return Settings(_env_file=None, **values)


STRONG = "x" * 48
OTHER = "y" * 48


def main() -> int:
    print("\n[secrets]")
    s = settings(jwt_secret="")
    check("S01 a blank JWT_SECRET means the development default, never an empty signing key",
          s.jwt_secret == DEV_JWT_SECRET, s.jwt_secret)
    # Security audit H5: the public development key is refused everywhere now.
    problems = settings(environment="development").production_problems()
    check("S02 development REFUSES the public default JWT key (audit H5)",
          any("JWT_SECRET" in p for p in problems), problems)
    check("S02b development with ALLOW_DEV_SECRET=true starts on the defaults (throwaway DB only)",
          settings(environment="development", allow_dev_secret=True).production_problems() == [])
    problems = settings(environment="production", allow_dev_secret=True).production_problems()
    check("S02c ALLOW_DEV_SECRET is ignored outside development", any("JWT_SECRET" in p for p in problems), problems)
    check("S02d development with strong, distinct secrets starts even with DEBUG on",
          settings(environment="development", jwt_secret=STRONG, secrets_key=OTHER, debug=True).production_problems() == [])

    problems = settings(environment="production").production_problems()
    check("S03 production refuses the default JWT secret", any("JWT_SECRET" in p for p in problems), problems)
    check("S04 …and a missing SECRETS_KEY", any("SECRETS_KEY" in p for p in problems), problems)
    check("S05 …and DEBUG left on", any("DEBUG" in p for p in problems), problems)

    problems = settings(environment="production", jwt_secret="short-secret", secrets_key=OTHER, debug=False).production_problems()
    check("S06 production refuses a short JWT secret", any("JWT_SECRET" in p for p in problems), problems)
    problems = settings(environment="production", jwt_secret=STRONG, secrets_key=STRONG, debug=False).production_problems()
    check("S07 production refuses SECRETS_KEY equal to JWT_SECRET", any("SECRETS_KEY" in p for p in problems), problems)
    problems = settings(environment="production", jwt_secret=STRONG, secrets_key=OTHER, debug=False).production_problems()
    check("S08 production with strong, distinct secrets and DEBUG off starts", problems == [], problems)

    print("\n[secrets manager]")
    from unittest import mock

    from app.core import config, secrets_manager

    secret = {"DATABASE_URL": "postgresql+asyncpg://o:p@h/db", "APP_DATABASE_URL": "postgresql+asyncpg://a:p@h/db",
              "PLATFORM_DATABASE_URL": "postgresql+asyncpg://pl:p@h/db", "JWT_SECRET": STRONG, "SECRETS_KEY": OTHER,
              "SMTP_PASSWORD": "", "SOMETHING_NEW": "ignored"}
    base = settings(secrets_manager_secret_id="inventoryai/backend", jwt_secret="from-env-file")
    with mock.patch.object(secrets_manager, "fetch_raw", return_value=dict(secret)):
        overrides = secrets_manager.load_overrides(base)
    check("M01 secret keys map to settings fields; unknown keys are ignored",
          overrides.get("jwt_secret") == STRONG and "something_new" not in overrides, sorted(overrides))
    with mock.patch.object(secrets_manager, "fetch_raw", return_value={**secret, "JWT_SECRET": ""}):
        try:
            secrets_manager.load_overrides(base)
            check("M02 a secret missing JWT_SECRET stops startup", False, "no error")
        except secrets_manager.SecretsUnavailableError as exc:
            check("M02 a secret missing JWT_SECRET stops startup", "JWT_SECRET" in str(exc), exc)
    with mock.patch.object(secrets_manager, "fetch_raw", side_effect=secrets_manager.SecretsUnavailableError("down")), \
            mock.patch.object(config, "Settings", lambda **kw: settings(secrets_manager_secret_id="x", **kw)):
        config.get_settings.cache_clear()
        try:
            config.get_settings()
            check("M03 an unreachable Secrets Manager stops startup (fail closed)", False, "started")
        except secrets_manager.SecretsUnavailableError:
            check("M03 an unreachable Secrets Manager stops startup (fail closed)", True)
    with mock.patch.object(secrets_manager, "fetch_raw", return_value=dict(secret)), \
            mock.patch.object(config, "Settings", lambda **kw: settings(**{"secrets_manager_secret_id": "x", "jwt_secret": "env", **kw})):
        config.get_settings.cache_clear()
        loaded = config.get_settings()
        check("M04 Secrets Manager values win over .env", loaded.jwt_secret == STRONG and loaded.secrets_key == OTHER,
              loaded.jwt_secret[:6])
    with mock.patch.object(secrets_manager, "fetch_raw", return_value=dict(secret)), \
            mock.patch.object(config, "Settings", lambda **kw: settings(**{"secrets_manager_secret_id": "x", **kw})), \
            mock.patch.dict("os.environ", {"DATABASE_URL": "postgresql+asyncpg://t:t@h/inventoryai_test"}):
        config.get_settings.cache_clear()
        loaded = config.get_settings()
        check("M05 a real environment variable still wins over the secret (test runner safety)",
              loaded.database_url.endswith("/inventoryai_test") and loaded.jwt_secret == STRONG, loaded.database_url)
    config.get_settings.cache_clear()

    try:
        settings(rate_limit_login="lots")
        check("S09 a malformed rate limit is refused at startup", False, "accepted")
    except ValueError:
        check("S09 a malformed rate limit is refused at startup", True)

    print("\n[rules]")
    check("R01 '10/1m'", Rule.parse("10/1m") == Rule(10, 60))
    check("R02 '20/15m'", Rule.parse("20/15m") == Rule(20, 900))
    check("R03 '100/1h' and '5/30s'", Rule.parse("100/1h") == Rule(100, 3600) and Rule.parse("5/30s") == Rule(5, 30))
    check("R04 '10/minute' reads as one minute", Rule.parse("10/minute") == Rule(10, 60))
    for bad in ("", "ten/1m", "0/1m", "10/1d"):
        try:
            Rule.parse(bad)
            check(f"R05 '{bad}' is refused", False)
        except ValueError:
            check(f"R05 '{bad}' is refused", True)

    print("\n[sliding window]")
    lim, rule = SlidingWindowLimiter(), Rule(3, 60)
    allowed = [lim.hit("k", rule, now=t) for t in (0, 1, 2)]
    check("W01 the first three attempts pass", allowed == [0, 0, 0], allowed)
    wait = lim.hit("k", rule, now=3)
    check("W02 the fourth is refused, with the wait until the oldest expires", wait == 57, wait)
    check("W03 a refused attempt does not extend the wait", lim.hit("k", rule, now=30) == 30)
    check("W04 once the window slides past, attempts pass again", lim.hit("k", rule, now=60.5) == 0)
    check("W05 keys are counted separately", lim.hit("other", rule, now=3) == 0)
    small = SlidingWindowLimiter(max_keys=4)
    for i in range(10):
        small.hit(f"flood-{i}", Rule(1, 60), now=i)
    check("W06 a flood of distinct keys cannot grow memory without bound", len(small._hits) <= 4, len(small._hits))

    print("\n[enforcement]")
    s = get_settings()
    saved = (s.rate_limit_enabled, s.rate_limit_login, s.rate_limit_login_account)
    s.rate_limit_enabled, s.rate_limit_login, s.rate_limit_login_account = True, "5/1m", "2/1m"
    rate_limit.limiter.reset()
    try:
        def request(ip: str) -> Request:
            return Request({"type": "http", "method": "POST", "path": "/auth/login", "headers": [], "client": (ip, 5000)})

        def attempt(ip: str, account: str):
            try:
                rate_limit.enforce(request(ip), "login", account=account)
                return None
            except ApiError as e:
                return e

        results = [attempt("10.0.0.1", "a@x.test") for _ in range(3)]
        err = results[2]
        check("E01 one client and one account: the third counted request in a minute is refused",
              results[0] is None and results[1] is None and err is not None, results)
        check("E02 …with 429 RATE_LIMITED and a Retry-After header",
              err is not None and err.status_code == 429 and err.code == "RATE_LIMITED"
              and int(err.headers["Retry-After"]) > 0, err and (err.status_code, err.code, err.headers))
        check("E03 account names are compared case-insensitively", attempt("10.0.0.1", " A@X.test ") is not None)
        check("E04 another client is unaffected", attempt("10.0.0.2", "a@x.test") is None)
        others = [attempt("10.0.0.1", f"user{i}@x.test") for i in range(4)]
        check("E05 one client trying many accounts hits the per-client limit",
              others[:2] == [None, None] and others[-1] is not None, others)

        print("\n[sign-in counts failures only]")
        rate_limit.limiter.reset()
        req = request("10.0.0.9")
        for _ in range(20):  # twenty successful sign-ins: never counted
            rate_limit.refuse_if_exhausted(req, "login", account="busy@x.test")
        check("F01 successful sign-ins are never throttled", True)
        rate_limit.record_failure(req, "login", account="busy@x.test")
        rate_limit.record_failure(req, "login", account="busy@x.test")
        try:
            rate_limit.refuse_if_exhausted(req, "login", account="busy@x.test")
            check("F02 two failures for one account use up its allowance", False)
        except ApiError as e:
            check("F02 two failures for one account use up its allowance", e.status_code == 429)
        try:
            rate_limit.refuse_if_exhausted(req, "login", account="someone.else@x.test")
            check("F03 …while the same client can still sign in to another account", True)
        except ApiError:
            check("F03 …while the same client can still sign in to another account", False)

        s.rate_limit_enabled = False
        check("E06 RATE_LIMIT_ENABLED=false turns it off", attempt("10.0.0.1", "a@x.test") is None)
    finally:
        s.rate_limit_enabled, s.rate_limit_login, s.rate_limit_login_account = saved
        rate_limit.limiter.reset()

    print(f"\n{passed} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
