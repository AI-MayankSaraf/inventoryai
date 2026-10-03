"""
Application settings, loaded from environment variables / .env.

Auth secrets, email, the AI pipeline, the extraction worker and S3 object
storage are all read from here. Redis remains a declared-but-unread
placeholder: the mapping cache is documented future work, not something
this build depends on. (The worker queue is a Postgres table.)
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: The old fallback signing key. It is printed right here in the source, so a
#: token signed with it can be forged by anyone (security audit H5). The API
#: now refuses to start with it in every environment, unless a developer sets
#: ALLOW_DEV_SECRET=true on their own laptop for a throwaway database.
DEV_JWT_SECRET = "dev-secret-change-me"
#: 32 random bytes is what HS256 needs to be unguessable.
MIN_SECRET_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "InventoryAI"
    environment: str = Field(default="development")
    debug: bool = Field(default=True)

    # ------------------------------------------------------- Secrets Manager
    # Where the passwords and keys live (app/core/secrets_manager.py). When
    # set, `get_settings()` reads this secret at startup and its values win
    # over `.env`; if it cannot be read the process refuses to start.
    # Blank = read everything from the environment (the old behaviour).
    secrets_manager_secret_id: str = Field(default="")
    # Blank = use AWS_ENDPOINT_URL (Floci serves S3 and Secrets Manager on
    # the same port), and on real AWS both stay blank.
    secrets_manager_endpoint_url: str = Field(default="")
    # Escape hatch for a throwaway local database only: lets the API start on
    # the public development JWT key. Ignored outside development.
    allow_dev_secret: bool = Field(default=False)

    # Postgres — asyncpg driver. Three roles, three purposes (see
    # alembic/versions/..._rls_policies.py for why): `database_url` is the
    # schema-owning role Alembic migrates with — it owns every table and so
    # bypasses RLS by default, which is correct for DDL/migrations but wrong
    # for anything request-scoped. `app_database_url` is what every ordinary
    # per-request tenant session uses — NOT the owner, NOT BYPASSRLS, so
    # every query it runs is actually subject to the RLS policies.
    # `platform_database_url` is BYPASSRLS, for the handful of things that
    # legitimately need to see across tenants: seeding, auth/refresh-token
    # lookups (which happen before any tenant is known), and impersonation.
    database_url: str = Field(
        default="postgresql+asyncpg://inventoryai:inventoryai_dev@localhost:5432/inventoryai"
    )
    app_database_url: str = Field(
        default="postgresql+asyncpg://inventoryai_app:inventoryai_app_dev@localhost:5432/inventoryai"
    )
    platform_database_url: str = Field(
        default="postgresql+asyncpg://inventoryai_platform:inventoryai_platform_dev@localhost:5432/inventoryai"
    )
    database_echo: bool = Field(default=False)

    jwt_secret: str = Field(default=DEV_JWT_SECRET)
    # Key for encrypting secrets at rest (currently per-company SMTP
    # passwords, via pgcrypto). Must be its own value (production_problems);
    # the fallback to `jwt_secret` survives only for ALLOW_DEV_SECRET
    # laptops. Rotating it makes stored SMTP passwords unreadable unless they
    # are re-encrypted — `scripts/secrets_manager.py push` does that.
    secrets_key: str = Field(default="")
    jwt_access_ttl_minutes: int = Field(default=15)

    @field_validator("jwt_secret", mode="before")
    @classmethod
    def _blank_secret_is_the_dev_default(cls, value: object) -> object:
        # `JWT_SECRET=` in .env is an empty string, not "unset" — and an
        # empty HMAC key signs tokens anyone can forge.
        if isinstance(value, str):
            return value.strip() or DEV_JWT_SECRET
        return value
    jwt_refresh_ttl_days: int = Field(default=30)

    # BR-AUTH-03: "5 failed attempts → 15-minute lock on the account."
    # Configurable, but these are the documented defaults.
    login_max_failed_attempts: int = Field(default=5)
    login_lockout_minutes: int = Field(default=15)

    # Per-client request limits (app/core/rate_limit.py), on top of the
    # account lockout above. Written as "<count>/<window>", e.g. "10/1m",
    # "30/15m", "100/1h". `_account` limits count one client and one email
    # address together. Sign-in and reset-password limits count FAILED
    # attempts only, so many people signing in from one office address are
    # never throttled; forgot-password counts every request (each one sends
    # an email).
    rate_limit_enabled: bool = Field(default=True)
    rate_limit_login: str = Field(default="30/15m")
    rate_limit_login_account: str = Field(default="10/15m")
    rate_limit_forgot_password: str = Field(default="30/15m")
    rate_limit_forgot_password_account: str = Field(default="5/15m")
    rate_limit_reset_password: str = Field(default="30/15m")
    rate_limit_supplier_login: str = Field(default="30/15m")
    rate_limit_supplier_login_account: str = Field(default="10/15m")

    @field_validator(
        "rate_limit_login", "rate_limit_login_account", "rate_limit_forgot_password",
        "rate_limit_forgot_password_account", "rate_limit_reset_password",
        "rate_limit_supplier_login", "rate_limit_supplier_login_account",
    )
    @classmethod
    def _rate_limit_parses(cls, value: str) -> str:
        from app.core.rate_limit import Rule  # imports this module

        Rule.parse(value)  # a typo fails at startup, not on the first sign-in
        return value

    # Email. `console` prints the message and records it as sent — the
    # development default, so invitations work with no mail server. `smtp`
    # sends for real. Anything else is rejected at startup.
    email_provider: str = Field(default="console")
    email_from: str = Field(default="no-reply@inventoryai.local")
    email_from_name: str = Field(default="InventoryAI")
    smtp_host: str = Field(default="")
    smtp_port: int = Field(default=587)
    smtp_username: str = Field(default="")
    smtp_password: str = Field(default="")
    smtp_use_tls: bool = Field(default=True)

    # Where invitation links point. The API never builds UI routes from the
    # request host — a forged Host header would otherwise mint invite links
    # pointing at an attacker's site.
    app_base_url: str = Field(default="http://localhost:3000")

    # Browsers enforce CORS on every fetch the frontend makes, so without
    # this every request from the Next.js dev server — including the login
    # POST — is refused before it even reaches a route. Comma-separated, not
    # a JSON list, to keep a one-line .env override simple. `localhost` and
    # `127.0.0.1` are different origins to a browser even on the same
    # machine/port, so both are listed for whichever the frontend happens to
    # be opened at.
    cors_allowed_origins: str = Field(default="http://localhost:3000,http://127.0.0.1:3000")

    @property
    def cors_allowed_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    # ------------------------------------------------------------ AI pipeline
    #
    # Uploaded document bytes live in S3 and nowhere else (BR-DOC-03).
    # There is no local-disk setting any more: a disk fallback is what
    # silently ships unencrypted customer documents when S3 is
    # misconfigured, so a misconfigured install refuses to start instead.
    document_max_bytes: int = Field(default=20 * 1024 * 1024)  # BR-DOC-01

    # The model rungs of the match ladder and OCR for scanned images.
    # `none` means the deterministic rungs (exact SKU, supplier alias,
    # barcode, normalisation rules, trigram) are the whole ladder and
    # anything they cannot settle goes to a human — which is the honest
    # behaviour, not a degraded one. Setting a provider here is what turns
    # the embedding/LLM rungs on; `ai/providers.py` is the seam.
    #: `none`, `ollama` (local, no key) or `openai` (any OpenAI-compatible
    #: API — OpenAI itself, Azure, Groq, vLLM, LM Studio…).
    ai_provider: str = Field(default="none")
    #: Blank means the provider's default (Ollama: http://localhost:11434,
    #: OpenAI: https://api.openai.com). No path — the client adds it.
    ai_base_url: str = Field(default="")
    ai_api_key: str = Field(default="")
    ai_model_small: str = Field(default="")
    ai_model_large: str = Field(default="")
    ai_embedding_model: str = Field(default="")
    #: Expected vector length from the embedding model; 0 skips the check.
    ai_embedding_dimensions: int = Field(default=0)
    #: Per request. A person is waiting on the screen, so a model that
    #: takes longer than this is abandoned and the step falls back to
    #: rules and manual mapping rather than hanging.
    ai_timeout_seconds: float = Field(default=60)
    #: `none` or `tesseract` (local, free). Reads scanned images and
    #: image-only PDFs, and rebuilds their item tables.
    ocr_provider: str = Field(default="none")
    #: Full path to tesseract.exe when it isn't on PATH.
    ocr_tesseract_cmd: str = Field(default="")
    #: Folder holding the *.traineddata language files; blank = Tesseract's own.
    ocr_tessdata_dir: str = Field(default="")
    #: Tesseract language codes joined with "+", e.g. "eng+hin".
    ocr_languages: str = Field(default="eng")
    #: Pages read from one scanned PDF (each page takes a few seconds).
    ocr_max_pages: int = Field(default=10)

    #: Where uploaded documents are read (app/modules/ai/worker.py).
    #: `embedded`: a worker loop inside each API process — nothing else to
    #: run. `external`: the API only queues; run `python -m app.worker`
    #: (the Docker `worker` service) so OCR never competes with requests.
    extraction_worker: str = Field(default="embedded")
    #: Seconds an idle worker waits before looking at the queue again.
    worker_poll_seconds: float = Field(default=2.0)
    #: A job running longer than this is presumed abandoned by a dead worker.
    worker_stale_after_minutes: int = Field(default=15)
    #: Times a job is put back after its worker died before it is given up.
    worker_max_retries: int = Field(default=3)

    @field_validator("extraction_worker")
    @classmethod
    def _known_worker_mode(cls, value: str) -> str:
        if value not in {"embedded", "external"}:
            raise ValueError("EXTRACTION_WORKER must be 'embedded' or 'external'")
        return value

    #: A trigram match at or above this is worth showing as a candidate.
    #: Below it the row is noise (08_AI_DATA_MODEL.md §4.3 rung 5).
    ai_trigram_floor: float = Field(default=0.28)
    #: Cosine similarity at or above which a product is offered as a
    #: semantic suggestion (rung 6). Measured with nomic-embed-text on a
    #: trade catalogue: right answers scored 0.67-0.83, unrelated items at
    #: most 0.54. Re-check it if AI_EMBEDDING_MODEL changes.
    ai_embedding_floor: float = Field(default=0.60)
    #: How many candidates the review screen is offered per line.
    ai_candidate_limit: int = Field(default=5)

    # ------------------------------------------------------------ S3 storage
    #
    # Every uploaded file — quotations, proformas, tax invoices, purchase
    # orders, rate lists — is a `documents` row plus one private S3 object.
    # `s3_bucket` empty means storage is unconfigured and the app refuses to
    # boot (app/core/storage.py:assert_ready); it is not a "disable uploads"
    # switch.
    s3_bucket: str = Field(default="")
    aws_region: str = Field(default="ap-south-1")

    # Credentials. Left empty on AWS so the instance/task role is used —
    # filling these in on a server means a long-lived key on disk, which is
    # the thing IAM roles exist to avoid. Set them for LocalStack/MinIO.
    aws_access_key_id: str = Field(default="")
    aws_secret_access_key: str = Field(default="")

    # A non-AWS S3 endpoint (LocalStack, MinIO). Empty on real AWS. Setting
    # it also forces path-style addressing, because
    # `http://bucket.localhost:4566` does not resolve.
    aws_endpoint_url: str = Field(default="")

    # BR-DOC-03, the encryption half. `AES256` is SSE-S3: bucket-managed
    # keys, no key administration, no per-request cost. `aws:kms` with
    # `s3_kms_key_id` gives auditable key usage and rotation at KMS prices.
    # Anything else is rejected at startup.
    s3_sse: str = Field(default="AES256")
    s3_kms_key_id: str = Field(default="")

    # BR-DOC-03, the expiry half: "downloads are pre-signed and expire in
    # 5 minutes."
    s3_presign_ttl_seconds: int = Field(default=300)

    # botocore `standard` retry mode: exponential backoff on throttling and
    # 5xx, nothing on a 4xx that would only fail again.
    s3_max_attempts: int = Field(default=3)
    s3_connect_timeout_seconds: int = Field(default=5)
    s3_read_timeout_seconds: int = Field(default=30)

    # Placeholders for later phases — not read yet. Redis is explicitly out
    # of scope: the cache design in 08_AI_DATA_MODEL.md stays as written,
    # nothing depends on it, and mappings are read from Postgres each time.
    redis_url: str = Field(default="redis://localhost:6379/0")

    @property
    def is_development(self) -> bool:
        return self.environment.lower() in {"development", "dev", "local", "test"}

    @property
    def dev_secret_allowed(self) -> bool:
        return self.is_development and self.allow_dev_secret

    def production_problems(self) -> list[str]:
        """What makes this configuration unsafe to start with.

        Since security audit H5 the secret checks apply in development too:
        a laptop API reachable over Wi-Fi with the public key in the source
        lets anyone on that network sign in as the platform admin. Only
        DEBUG stays allowed in development. ALLOW_DEV_SECRET=true (development
        only) switches the secret checks off for a throwaway database."""
        problems = []
        if self.dev_secret_allowed:
            return problems
        if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < MIN_SECRET_LENGTH:
            problems.append(
                f"JWT_SECRET is the development default or shorter than {MIN_SECRET_LENGTH} characters, "
                "so anyone could forge a sign-in token."
            )
        if len(self.secrets_key) < MIN_SECRET_LENGTH or self.secrets_key == self.jwt_secret:
            problems.append(
                f"SECRETS_KEY must be set to its own value of at least {MIN_SECRET_LENGTH} characters "
                "(it encrypts stored SMTP passwords; it must not be the JWT secret)."
            )
        if self.debug and not self.is_development:
            problems.append("DEBUG is on, which sends Python tracebacks to API callers. Set DEBUG=false.")
        return problems


@lru_cache
def get_settings() -> Settings:
    """Settings, in this order of precedence:

        1. real environment variables (a test runner pointing DATABASE_URL at
           the test database must never be overruled by the secret)
        2. the Secrets Manager secret, when SECRETS_MANAGER_SECRET_ID is set
        3. `backend/.env`
        4. the defaults above

    Built once per process. A secret that is configured but unreadable
    raises `SecretsUnavailableError`, so nothing starts on half a config."""
    settings = Settings()
    if not settings.secrets_manager_secret_id:
        return settings
    import os

    from app.core import secrets_manager

    overrides = secrets_manager.load_overrides(settings)
    from_environment = {name.lower() for name in os.environ}
    overrides = {field: value for field, value in overrides.items() if field not in from_environment}
    # Init values outrank `.env`; the environment's own values were removed
    # above, so they keep winning.
    return Settings(**overrides)
