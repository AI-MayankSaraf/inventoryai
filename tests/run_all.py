"""Run every InventoryAI test suite against a running stack, one at a time.

    backend/.venv/Scripts/python.exe tests/run_all.py            # everything
    backend/.venv/Scripts/python.exe tests/run_all.py --only api,backend
    backend/.venv/Scripts/python.exe tests/run_all.py --skip ai  # no Ollama here
    backend/.venv/Scripts/python.exe tests/run_all.py e2e_auth browser_roles
    backend/.venv/Scripts/python.exe tests/run_all.py --list
    backend/.venv/Scripts/python.exe tests/run_all.py --isolated           # own database (recommended)
    backend/.venv/Scripts/python.exe tests/run_all.py --isolated --reset   # ...rebuilt from scratch first

Suites run sequentially on purpose: several of them sign sessions out,
suspend test companies or change settings, and running two at once makes
the other one fail for reasons that have nothing to do with the code.

With --isolated the runner builds and starts its own stack (test_stack.py):
database inventoryai_test, API on :8010, frontend on :3010, stopped again at
the end, so test records never land in the everyday database. Without it the
suites need the backend (API_URL, default http://127.0.0.1:8000) and, for the
browser suites, the frontend (APP_URL, default http://localhost:3000) seeded
with `python -m app.db.seed --demo`. Run
it with the backend's Python so the suites find openpyxl, Pillow and the
app's settings. Exits non-zero if any suite fails.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
BACKEND = ROOT / "backend"
API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
APP_URL = os.environ.get("APP_URL", "http://localhost:3000")

# (name, group, needs) — `needs` names the optional services a suite relies
# on beyond Postgres, S3 and Mailpit: "ai" (an embedding provider such as
# Ollama) and "ocr" (Tesseract).
SUITES: list[tuple[str, str, set[str]]] = [
    ("verify_rls", "backend", set()),
    ("verify_s3", "backend", set()),
    ("verify_security_config", "backend", set()),
    ("e2e_auth", "backend", set()),
    ("e2e_roles", "backend", set()),
    ("e2e_multi_company", "backend", set()),
    ("e2e_platform", "backend", set()),
    ("e2e_receiving", "backend", set()),
    ("e2e_rfq_import", "backend", set()),
    ("e2e_supplier_catalogue", "backend", set()),
    ("e2e_ai_documents", "backend", set()),
    ("e2e_worker", "backend", set()),
    ("api_business_flow", "api", set()),
    ("api_endpoint_sweep", "api", set()),
    ("api_supplier_portal", "api", set()),
    ("api_ai_features", "api", {"ai"}),
    ("api_ocr", "api", {"ocr"}),
    ("browser_screen_walk", "browser", set()),
    ("browser_auth", "browser", set()),
    ("browser_receiving", "browser", set()),
    ("browser_supplier_catalogue", "browser", set()),
    ("browser_roles", "browser", set()),
    ("browser_ai_documents", "browser", set()),
    ("browser_platform", "browser", set()),
    ("browser_supplier_portal", "browser", set()),
    ("browser_godowns_numbering_register", "browser", set()),
    ("browser_lists_plans_records", "browser", set()),
]

SUMMARY = re.compile(r"(\d+)\s+passed,\s+(\d+)\s+failed|(\d+)/(\d+) checks passed|(\d+) unexpected failure")


def command(name: str, group: str) -> tuple[list[str], Path]:
    if group == "backend":
        args = [sys.executable, "-m", f"scripts.{name}"]
        if name.startswith("e2e_"):
            args.append(API_URL)
        return args, BACKEND
    if group == "api":
        return [sys.executable, str(TESTS / f"{name}.py")], ROOT
    return ["node", str(TESTS / f"{name}.js"), APP_URL], ROOT


def reachable(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            return r.status < 500
    except urllib.error.HTTPError as e:
        return e.code < 500
    except Exception:
        return False


def summary(output: str) -> str:
    matches = list(SUMMARY.finditer(output))
    if not matches:
        return ""
    m = matches[-1]
    if m.group(1):
        return f"{m.group(1)} passed, {m.group(2)} failed"
    if m.group(3):
        return f"{m.group(3)}/{m.group(4)} checks"
    return f"{m.group(5)} unexpected failure(s)"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help="run only these suites")
    parser.add_argument("--only", default="", help="comma-separated groups: backend, api, browser")
    parser.add_argument("--skip", default="", help="comma-separated needs to skip: ai, ocr")
    parser.add_argument("--list", action="store_true", help="list the suites and exit")
    parser.add_argument("--log-dir", default=str(TESTS / "logs"), help="where each suite's full output is saved")
    parser.add_argument("--timeout", type=int, default=900, help="seconds per suite")
    parser.add_argument("--isolated", action="store_true",
                        help="run on a separate test database, API (:8010) and frontend (:3010)")
    parser.add_argument("--reset", action="store_true", help="with --isolated: rebuild the test database first")
    opts = parser.parse_args()

    groups = {g for g in opts.only.split(",") if g}
    skip = {s for s in opts.skip.split(",") if s}
    unknown = set(opts.names) - {s[0] for s in SUITES}
    if unknown:
        parser.error(f"unknown suite(s): {', '.join(sorted(unknown))}")

    chosen, skipped = [], []
    for name, group, needs in SUITES:
        if opts.names and name not in opts.names:
            continue
        if groups and group not in groups:
            continue
        if needs & skip:
            skipped.append(name)
            continue
        chosen.append((name, group))

    if opts.list:
        for name, group, needs in SUITES:
            print(f"{group:8} {name:36} {', '.join(sorted(needs))}")
        return 0

    stack = None
    extra_env: dict[str, str] = {}
    if opts.isolated:
        global API_URL, APP_URL
        import test_stack

        test_stack.prepare(reset=opts.reset)
        stack = test_stack.Stack(frontend=any(g == "browser" for _n, g in chosen))
        try:
            stack.start()
        except Exception as e:
            stack.stop()
            print(e)
            return 2
        extra_env = test_stack.settings_env()
        API_URL, APP_URL = test_stack.API_URL, test_stack.APP_URL
    try:
        return _run(opts, chosen, skipped, skip, extra_env)
    finally:
        if stack:
            stack.stop()


def _run(opts, chosen, skipped, skip, extra_env) -> int:
    if not reachable(API_URL + "/health"):
        print(f"The backend is not answering at {API_URL}/health — start it first.")
        return 2
    if any(g == "browser" for _n, g in chosen) and not reachable(APP_URL + "/login"):
        print(f"The frontend is not answering at {APP_URL} — start it first.")
        return 2

    log_dir = Path(opts.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "API_URL": API_URL, "APP_URL": APP_URL, **extra_env}

    results = []
    started = time.monotonic()
    for name, group in chosen:
        args, cwd = command(name, group)
        print(f"-- {name} ...", end="", flush=True)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                args, cwd=cwd, env=env, capture_output=True, timeout=opts.timeout,
                encoding="utf-8", errors="replace",
            )
            output, code = proc.stdout + proc.stderr, proc.returncode
        except subprocess.TimeoutExpired as e:
            output = (e.stdout or b"").decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
            output += f"\nTIMED OUT after {opts.timeout}s"
            code = -1
        seconds = time.monotonic() - t0
        (log_dir / f"{name}.log").write_text(output, encoding="utf-8")
        # Belt and braces: a suite that reports failures fails, whatever its
        # exit code says.
        reported = SUMMARY.findall(output)
        last = reported[-1] if reported else None
        says_failed = bool(last) and ((last[1] and int(last[1]) > 0) or (last[4] and int(last[4]) > 0)
                                      or (last[2] and last[2] != last[3]))
        ok = code == 0 and not says_failed
        results.append((name, ok, seconds, summary(output)))
        print(f"\r{'ok  ' if ok else 'FAIL'} {name:36} {seconds:6.1f}s  {summary(output)}")
        if not ok:
            for line in [l for l in output.splitlines() if "FAIL" in l or "Error" in l][:10]:
                print(f"       {line[:200]}")

    failed = [r for r in results if not r[1]]
    print()
    print(f"{len(results) - len(failed)} of {len(results)} suites passed "
          f"in {(time.monotonic() - started) / 60:.1f} min. Logs: {log_dir}")
    if skipped:
        print(f"Skipped (--skip {','.join(sorted(skip))}): {', '.join(skipped)}")
    for name, *_ in failed:
        print(f"  FAILED: {name}  (see {log_dir / (name + '.log')})")
    if any("429" in (log_dir / f"{name}.log").read_text(encoding="utf-8") for name, *_ in failed):
        print("\nA suite was refused with 429. The suites make many failed sign-ins on purpose, so a few "
              "runs in quick succession use up the API's sign-in limits. Restart the API (the counters are "
              "in memory) or set RATE_LIMIT_ENABLED=false in backend/.env on a test machine.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
