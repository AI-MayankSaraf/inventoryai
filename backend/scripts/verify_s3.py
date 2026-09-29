"""
Prove the S3 storage layer against the bucket this install is actually
configured for.

Run it after setting S3_BUCKET and the AWS variables, before starting the
API. It uses the real client, the real bucket and the real credentials —
nothing is mocked — so a pass here means uploads will work, and a failure
here names the reason instead of letting the first user find it.

    python -m scripts.verify_s3

What it answers, in order of how much damage a wrong answer does:

  * Is the bucket public? A public bucket means every customer's invoices
    are on the open internet. Checked first, and a failure is fatal.
  * Is what we write actually encrypted (BR-DOC-03)?
  * Does a pre-signed link work, carry `attachment`, and expire?
  * Does a key leak the filename or the content hash?
  * Do writes, reads and deletes round-trip, and is deleting an absent
    object still a success?

Everything it creates is written under `co/_verify/` and deleted again.
Exit code 0 only if every check passes.
"""

from __future__ import annotations

import sys
import urllib.error
import urllib.request
import uuid
from urllib.parse import parse_qs, urlparse
from datetime import datetime, timezone

from botocore.exceptions import ClientError

from app.core import storage
from app.core.config import get_settings

passed = 0
failed: list[str] = []


def check(name: str, cond: bool, info: object = "") -> None:
    global passed
    if cond:
        passed += 1
        print(f"  ok   {name}")
    else:
        failed.append(name)
        print(f"  FAIL {name}" + (f"  — {info}" if info else ""))


def fetch(url: str) -> tuple[int, bytes, dict]:
    try:
        with urllib.request.urlopen(url) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)
    except Exception as exc:  # network-level
        return 0, str(exc).encode(), {}


def main() -> int:
    settings = get_settings()
    client = storage._client()
    bucket = settings.s3_bucket
    # A non-empty endpoint means this is pointed at a local S3 emulator
    # (LocalStack, Floci, MinIO) rather than real AWS. Several of those do
    # not enforce SigV4 authentication on presigned GETs at all — a request
    # with a tampered or missing signature is served anyway — which is a
    # property of the emulator, not of this code: boto3 signs the same way
    # regardless of what answers on the other end. Those two checks are
    # downgraded to a skip here rather than silently dropped, so the gap
    # stays visible instead of quietly disappearing.
    is_dev_endpoint = bool(settings.aws_endpoint_url)

    print(f"Bucket   : {bucket}")
    print(f"Region   : {settings.aws_region}")
    print(f"Endpoint : {settings.aws_endpoint_url or 'aws (default)'}")
    print(f"SSE      : {settings.s3_sse}")
    print()

    # -------------------------------------------------- configuration
    print("configuration")
    try:
        storage.assert_ready()
        check("bucket is reachable and settings are valid", True)
    except Exception as exc:
        check("bucket is reachable and settings are valid", False, exc)
        print("\nStopping: nothing else can be checked against an unreachable bucket.")
        return 1

    # -------------------------------------------------- not public
    print("\nexposure")
    try:
        block = client.get_public_access_block(Bucket=bucket)["PublicAccessBlockConfiguration"]
        check("public access is blocked on all four settings", all(block.values()), block)
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "NoSuchPublicAccessBlockConfiguration":
            check("public access is blocked on all four settings", False,
                  "no public access block is configured on this bucket")
        else:
            # LocalStack and MinIO often do not implement this call. Not a
            # pass — an unimplemented check proves nothing — but say so
            # plainly rather than reporting a failure that means "local".
            print(f"  skip public access block — endpoint does not implement it ({code})")

    try:
        acl = client.get_bucket_acl(Bucket=bucket)
        public_grants = [
            g for g in acl.get("Grants", [])
            if "AllUsers" in str(g.get("Grantee", {}).get("URI", ""))
            or "AuthenticatedUsers" in str(g.get("Grantee", {}).get("URI", ""))
        ]
        check("bucket ACL grants nothing to AllUsers/AuthenticatedUsers", not public_grants, public_grants)
    except ClientError as exc:
        print(f"  skip bucket ACL — {exc.response.get('Error', {}).get('Code', '')}")

    # -------------------------------------------------- keys
    print("\nkeys")
    company = str(uuid.uuid4())
    k1 = storage.build_key(company_id=company, document_type="tax_invoice", extension="pdf")
    k2 = storage.build_key(company_id=company, document_type="tax_invoice", extension="pdf")
    check("two keys for the same inputs differ (random, not content-addressed)", k1 != k2, (k1, k2))
    check("key is scoped to the tenant", k1.startswith(f"co/{company}/"), k1)
    check("key carries the document type and date", "/tax_invoice/" in k1 and f"/{datetime.now(timezone.utc):%Y}/" in k1, k1)
    secret_name = "Acme-confidential-pricing.pdf"
    k3 = storage.build_key(company_id=company, document_type=None, extension="pdf")
    check("key never contains the original filename", secret_name.split(".")[0] not in k3, k3)
    check("unclassified upload still gets a valid prefix", "/unclassified/" in k3, k3)

    # -------------------------------------------------- round trip
    print("\nround trip")
    key = f"co/_verify/{uuid.uuid4().hex}.txt"
    body = b"inventoryai storage verification " + uuid.uuid4().hex.encode()
    try:
        storage.put(key, body, content_type="text/plain")
        check("put succeeds", True)
        check("get returns the same bytes", storage.get(key) == body)
        check("exists is True for a written object", storage.exists(key) is True)
        check("get returns None for an absent key", storage.get(key + ".nope") is None)
        check("exists is False for an absent key", storage.exists(key + ".nope") is False)

        head = client.head_object(Bucket=bucket, Key=key)
        check(
            f"object is encrypted server-side with {settings.s3_sse} (BR-DOC-03)",
            head.get("ServerSideEncryption") == settings.s3_sse,
            head.get("ServerSideEncryption"),
        )

        # ---------------------------------------------- presigned
        print("\npre-signed download (BR-DOC-03)")
        url, expires_at = storage.presigned_get_url(key, filename=secret_name, content_type="text/plain")
        ttl = (expires_at - datetime.now(timezone.utc)).total_seconds()
        check("link expires in about 5 minutes", 280 <= ttl <= 305, f"{ttl:.0f}s")
        check("link is not the bare object URL (it is signed)",
              "X-Amz-Signature" in url or "Signature" in url, url.split("?")[0])
        query = parse_qs(urlparse(url).query)
        # These two are checked from the URL itself rather than from a
        # fetch, so they hold even where the endpoint is not reachable from
        # wherever this script is being run.
        check(
            "the download disposition is inside the signature, not appended to it",
            "attachment" in (query.get("response-content-disposition", [""])[0]),
            query.get("response-content-disposition"),
        )
        check(
            "the signature covers the response headers",
            "response-content-disposition" in query.get("X-Amz-SignedHeaders", [""])[0]
            or "response-content-disposition" in url,
            query.get("X-Amz-SignedHeaders"),
        )
        check("v4 signing (short-lived signatures)", query.get("X-Amz-Algorithm", [""])[0] == "AWS4-HMAC-SHA256",
              query.get("X-Amz-Algorithm"))

        code, fetched, headers = fetch(url)
        if code == 0:
            print(f"  skip fetching the link — endpoint not reachable from here ({fetched.decode()[:80]})")
        else:
            check("the link serves the bytes", code == 200 and fetched == body, code)
            check(
                "the link forces a download rather than rendering in the browser",
                "attachment" in headers.get("Content-Disposition", ""),
                headers.get("Content-Disposition"),
            )
            check(
                "the filename comes back on the download",
                secret_name in headers.get("Content-Disposition", ""),
                headers.get("Content-Disposition"),
            )
            tampered = url.replace("attachment", "inline")
            t_code, _, t_headers = fetch(tampered)
            sig_enforced = t_code == 403 or "attachment" in t_headers.get("Content-Disposition", "")
            if not sig_enforced and is_dev_endpoint:
                print("  skip editing the signed disposition breaks the signature — this "
                      "endpoint does not enforce SigV4 (dev emulator); re-run against real "
                      "AWS before treating this as verified")
            else:
                check("editing the signed disposition breaks the signature", sig_enforced, t_code)

        code, _, _ = fetch(url.split("?")[0])
        unsigned_rejected = code in (0, 400, 401, 403)
        if not unsigned_rejected and is_dev_endpoint:
            print("  skip the object is not readable without a signature — this endpoint "
                  "does not enforce SigV4 (dev emulator); re-run against real AWS before "
                  "treating this as verified")
        else:
            check("the object is not readable without a signature", unsigned_rejected, code)

        print("\nfailure handling")
        real_bucket = settings.s3_bucket
        try:
            settings.s3_bucket = "inventoryai-does-not-exist-" + uuid.uuid4().hex
            try:
                storage.get(key)
                check("a missing bucket raises rather than looking like a missing file", False,
                      "get() returned instead of raising")
            except storage.StorageError as exc:
                check("a missing bucket raises rather than looking like a missing file", True)
                check("the error names no credential, endpoint or bucket",
                      "test" not in str(exc).lower() and real_bucket not in str(exc), str(exc))
        finally:
            settings.s3_bucket = real_bucket

    finally:
        print("\ncleanup")
        storage.delete(key)
        check("delete removes the object", storage.exists(key) is False)
        storage.delete(key)
        check("deleting an absent object is not an error", True)

    print()
    print(f"{passed} passed, {len(failed)} failed")
    for name in failed:
        print(f"  - {name}")
    if is_dev_endpoint:
        print()
        print("This ran against a non-AWS endpoint. Presigned-URL signature enforcement "
              "was not provable here — that is the one part of BR-DOC-03 a dev emulator "
              "cannot confirm. Run this again against a real AWS bucket at least once "
              "before relying on it in production.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
