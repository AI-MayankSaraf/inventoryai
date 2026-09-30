"""
Per-client request limits for the endpoints a password guesser or a
mail-bomber would hammer: sign-in, forgot-password, reset-password and the
Supplier Portal sign-in.

This sits in front of, not instead of, the per-account lockout
(BR-AUTH-03: five failures lock an account for 15 minutes). The lockout
stops one account being guessed at; these limits stop one client trying
many accounts, flooding someone's inbox with reset emails, or keeping a
victim permanently locked out.

The counters live in this process's memory. That is exact for a single API
process (the Docker image runs one) and approximate with several — each
process counts separately. Behind a load balancer with many replicas, add
a shared limit there (or a WAF rule) as well.

The client is `request.client.host`. Behind a reverse proxy, start uvicorn
with `--proxy-headers --forwarded-allow-ips=<proxy address>` so that is the
caller's address rather than the proxy's; otherwise every user shares one
counter.
"""

from __future__ import annotations

import math
import re
import time
from collections import deque
from dataclasses import dataclass
from typing import Optional

from fastapi import Request, status

from app.core.config import get_settings
from app.core.errors import CODE_RATE_LIMITED, ApiError

_RULE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*([smh])\w*\s*$", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


@dataclass(frozen=True)
class Rule:
    limit: int
    window_seconds: int

    @classmethod
    def parse(cls, text: str) -> "Rule":
        """`"10/1m"`, `"20/15m"`, `"100/1h"`, `"5/30s"`; `"10/m"` means one minute."""
        match = _RULE.match(text or "")
        if not match:
            raise ValueError(f"Rate limit '{text}' should look like '10/1m', '20/15m' or '100/1h'")
        count, amount, unit = match.groups()
        window = int(amount or 1) * _UNIT_SECONDS[unit.lower()]
        if int(count) < 1 or window < 1:
            raise ValueError(f"Rate limit '{text}' must allow at least one request per window")
        return cls(int(count), window)


class SlidingWindowLimiter:
    """Counts attempts per key over a sliding window."""

    def __init__(self, max_keys: int = 50_000) -> None:
        self._hits: dict[str, tuple[int, deque[float]]] = {}
        self._max_keys = max_keys

    def hit(self, key: str, rule: Rule, now: Optional[float] = None) -> float:
        """Record one attempt. Returns 0 when it is allowed, otherwise the
        seconds until the next attempt would be."""
        return self.hit_all([(key, rule)], now)

    def hit_all(self, checks: list[tuple[str, Rule]], now: Optional[float] = None) -> float:
        """One attempt that must fit every (key, rule). It is counted against
        all of them only when all allow it, so a refused attempt uses up
        nothing and waiting out the window always works."""
        wait = self.wait(checks, now)
        if not wait:
            self.record(checks, now)
        return wait

    def wait(self, checks: list[tuple[str, Rule]], now: Optional[float] = None) -> float:
        """Seconds until every (key, rule) has room again; 0 if it has now.
        Counts nothing."""
        now = time.monotonic() if now is None else now
        wait = 0.0
        for key, rule in checks:
            hits = self._queue(key, rule, now)
            if len(hits) >= rule.limit:
                wait = max(wait, hits[0] + rule.window_seconds - now, 0.001)
        return wait

    def record(self, checks: list[tuple[str, Rule]], now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        for key, rule in checks:
            self._queue(key, rule, now).append(now)

    def _queue(self, key: str, rule: Rule, now: float) -> deque[float]:
        entry = self._hits.get(key)
        if entry is None:
            if len(self._hits) >= self._max_keys:
                self._sweep(now)
            entry = self._hits[key] = (rule.window_seconds, deque())
        hits = entry[1]
        while hits and hits[0] <= now - rule.window_seconds:
            hits.popleft()
        return hits

    def _sweep(self, now: float) -> None:
        """Drop keys with nothing left in their window; if a flood of
        distinct keys leaves too many, drop the oldest half."""
        for key in [k for k, (w, h) in self._hits.items() if not h or h[-1] <= now - w]:
            del self._hits[key]
        if len(self._hits) >= self._max_keys:
            oldest = sorted(self._hits, key=lambda k: self._hits[k][1][-1])
            for key in oldest[: len(oldest) // 2]:
                del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


limiter = SlidingWindowLimiter()


def client_address(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _checks(request: Request, scope: str, account: Optional[str]) -> list[tuple[str, Rule]]:
    settings = get_settings()
    address = client_address(request)
    checks = [(f"{scope}|{address}", Rule.parse(getattr(settings, f"rate_limit_{scope}")))]
    if account is not None:
        checks.append(
            (f"{scope}|{address}|{account.strip().lower()}",
             Rule.parse(getattr(settings, f"rate_limit_{scope}_account")))
        )
    return checks


def _refuse(wait: float) -> None:
    seconds = math.ceil(wait)
    raise ApiError(
        status.HTTP_429_TOO_MANY_REQUESTS,
        CODE_RATE_LIMITED,
        f"Too many attempts. Try again in {_readable(seconds)}.",
        headers={"Retry-After": str(seconds)},
    )


def enforce(request: Request, scope: str, *, account: Optional[str] = None) -> None:
    """Count this request and refuse it with 429 RATE_LIMITED once the
    client (and, with `account`, the client and account together) has used
    up the `rate_limit_<scope>` / `rate_limit_<scope>_account` allowance.
    For requests that cost something every time, e.g. sending an email."""
    if not get_settings().rate_limit_enabled:
        return
    wait = limiter.hit_all(_checks(request, scope, account))
    if wait:
        _refuse(wait)


def refuse_if_exhausted(request: Request, scope: str, *, account: Optional[str] = None) -> None:
    """Refuse with 429 when this client has no failures left, without
    counting this request. Pair with `record_failure`: sign-in limits count
    only failed attempts, so an office behind one address can sign in all
    day while a password guesser is stopped."""
    if not get_settings().rate_limit_enabled:
        return
    wait = limiter.wait(_checks(request, scope, account))
    if wait:
        _refuse(wait)


def record_failure(request: Request, scope: str, *, account: Optional[str] = None) -> None:
    if get_settings().rate_limit_enabled:
        limiter.record(_checks(request, scope, account))


def _readable(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds} second{'s' if seconds != 1 else ''}"
    minutes = math.ceil(seconds / 60)
    return f"{minutes} minute{'s' if minutes != 1 else ''}"
