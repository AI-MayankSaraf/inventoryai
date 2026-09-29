"""
Error responses — RFC 9457 problem+json, per 04_API_SPECIFICATION.md §1:

    { "type", "title", "status", "detail", "code",
      "errors": [{"field","message"}], "request_id" }

The `code` is the part that matters to callers. FastAPI's default error body
is `{"detail": "..."}`, a human string a client can only match on by
substring — which breaks the moment anyone rewords a message. The spec
instead defines a fixed code vocabulary (`GODOWN_OUT_OF_SCOPE`,
`RATE_LIMITED`, `LAST_OWNER`…) so the frontend can branch on the code and
show the message.

`ApiError` is what handlers raise when they want a specific code.
Everything else — plain `HTTPException`s, FastAPI's own validation errors —
is mapped onto the same envelope by the handlers below, so a client never
has to parse two different error shapes.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from fastapi import HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

# 04_API_SPECIFICATION.md §1 "Standard error codes".
CODE_VALIDATION = "VALIDATION_ERROR"
CODE_UNAUTHENTICATED = "UNAUTHENTICATED"
CODE_TOKEN_EXPIRED = "TOKEN_EXPIRED"
CODE_FORBIDDEN = "FORBIDDEN"
CODE_GODOWN_OUT_OF_SCOPE = "GODOWN_OUT_OF_SCOPE"
CODE_TENANT_MISMATCH = "TENANT_MISMATCH"
CODE_SESSION_REVOKED = "SESSION_REVOKED"
CODE_INVALID_RESET_TOKEN = "INVALID_RESET_TOKEN"
CODE_NOT_FOUND = "NOT_FOUND"
CODE_DUPLICATE = "DUPLICATE"
CODE_RECORD_IN_USE = "RECORD_IN_USE"
CODE_STALE_RECORD = "STALE_RECORD"
CODE_INVALID_STATE_TRANSITION = "INVALID_STATE_TRANSITION"
CODE_BUSINESS_RULE_VIOLATION = "BUSINESS_RULE_VIOLATION"
CODE_RATE_LIMITED = "RATE_LIMITED"

# Codes named directly by 06_BUSINESS_RULES.md that aren't in the generic
# table above.
CODE_INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
CODE_COMPANY_SUSPENDED = "COMPANY_SUSPENDED"
CODE_PASSWORD_TOO_WEAK = "PASSWORD_TOO_WEAK"
CODE_ROLE_ESCALATION = "ROLE_ESCALATION"
CODE_LAST_OWNER = "LAST_OWNER"
CODE_INVITE_EXPIRED = "INVITE_EXPIRED"
CODE_ALREADY_ACCEPTED = "ALREADY_ACCEPTED"
CODE_NOT_A_MEMBER = "NOT_A_MEMBER"

# RFQ -> PO -> GRN procurement loop (06_BUSINESS_RULES.md §5, 7, 9, 4).
CODE_NO_ITEMS = "NO_ITEMS"
CODE_SUPPLIER_EMAIL_MISSING = "SUPPLIER_EMAIL_MISSING"
CODE_APPROVAL_LIMIT_EXCEEDED = "APPROVAL_LIMIT_EXCEEDED"
CODE_PO_CANCELLED = "PO_CANCELLED"
CODE_PO_HAS_RECEIPTS = "PO_HAS_RECEIPTS"
CODE_EXCESS_RECEIPT_NOT_ALLOWED = "EXCESS_RECEIPT_NOT_ALLOWED"
CODE_EXPECTED_VARIANT_REQUIRED = "EXPECTED_VARIANT_REQUIRED"
CODE_REMARKS_REQUIRED = "REMARKS_REQUIRED"
CODE_GRN_CONFIRMED = "GRN_CONFIRMED"
CODE_INVALID_PO_STATE = "INVALID_PO_STATE"
CODE_INSUFFICIENT_STOCK = "INSUFFICIENT_STOCK"
CODE_SAME_GODOWN = "SAME_GODOWN"
CODE_IMMUTABLE_LEDGER = "IMMUTABLE_LEDGER"
CODE_NO_UOM_CONVERSION = "NO_UOM_CONVERSION"
CODE_BATCH_REQUIRED = "BATCH_REQUIRED"
CODE_BATCH_EXPIRED = "BATCH_EXPIRED"
CODE_PERIOD_CLOSED = "PERIOD_CLOSED"

# Supplier quotations and comparison (06_BUSINESS_RULES.md §6, BR-QT/BR-CMP).
CODE_QUOTATION_EXPIRED = "QUOTATION_EXPIRED"
CODE_APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
CODE_UNRESOLVED_LINES = "UNRESOLVED_LINES"
CODE_INCOMPARABLE = "INCOMPARABLE"

# Proforma, supplier invoice and purchase return (§8, §2.14, §2.15).
CODE_VARIANCE_EXCEEDS_TOLERANCE = "VARIANCE_EXCEEDS_TOLERANCE"
CODE_ALREADY_MATCHED = "ALREADY_MATCHED"
CODE_RETURN_EXCEEDS_RECEIPT = "RETURN_EXCEEDS_RECEIPT"
CODE_INVOICE_DISPUTED = "INVOICE_DISPUTED"

_DEFAULT_CODES = {
    400: CODE_VALIDATION,
    401: CODE_UNAUTHENTICATED,
    403: CODE_FORBIDDEN,
    404: CODE_NOT_FOUND,
    409: CODE_DUPLICATE,
    422: CODE_BUSINESS_RULE_VIOLATION,
    429: CODE_RATE_LIMITED,
}

_TITLES = {
    400: "Bad Request",
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    422: "Unprocessable Entity",
    429: "Too Many Requests",
    500: "Internal Server Error",
}


class ApiError(HTTPException):
    """An HTTPException that also carries the spec's error `code`, and
    optionally a `Retry-After` header for 429s."""

    def __init__(
        self,
        status_code: int,
        code: str,
        detail: str,
        *,
        errors: Optional[list[dict[str, str]]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.errors = errors or []


def _problem(
    *,
    status_code: int,
    code: str,
    detail: Any,
    request: Request,
    errors: Optional[list[dict[str, str]]] = None,
    headers: Optional[dict[str, str]] = None,
) -> JSONResponse:
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    body = {
        # `about:blank` is RFC 9457's own default for "no type-specific
        # documentation page" — honest until there is a docs URL to point at.
        "type": "about:blank",
        "title": _TITLES.get(status_code, "Error"),
        "status": status_code,
        "detail": detail if isinstance(detail, str) else str(detail),
        "code": code,
        "errors": errors or [],
        "request_id": request_id,
    }
    return JSONResponse(
        status_code=status_code,
        content=body,
        media_type="application/problem+json",
        headers=headers,
    )


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return _problem(
        status_code=exc.status_code,
        code=exc.code,
        detail=exc.detail,
        request=request,
        errors=exc.errors,
        headers=exc.headers,
    )


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Plain HTTPExceptions still come out in the documented shape — they
    just fall back to the default code for their status."""
    return _problem(
        status_code=exc.status_code,
        code=getattr(exc, "code", None) or _DEFAULT_CODES.get(exc.status_code, "ERROR"),
        detail=exc.detail,
        request=request,
        headers=exc.headers,
    )


async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Pydantic's field errors become the spec's `errors: [{field, message}]`
    rather than its own nested `loc`/`msg`/`ctx` structure."""
    errors = [
        {
            # Drop the leading "body"/"query" segment: the client knows where
            # it put the field, it just needs the name.
            "field": ".".join(str(p) for p in err.get("loc", [])[1:]) or str(err.get("loc", ["?"])[0]),
            "message": err.get("msg", "Invalid value"),
        }
        for err in exc.errors()
    ]
    return _problem(
        status_code=status.HTTP_400_BAD_REQUEST,
        code=CODE_VALIDATION,
        detail="One or more fields are invalid",
        request=request,
        errors=errors,
    )
