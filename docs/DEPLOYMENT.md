# Deploying InventoryAI

The stack is five containers: Postgres (with pgvector), a one-shot
`migrate` job, the API, the document worker and the web app. Object storage (S3) and email
(SMTP) are services you already have and point it at.

```text
browser ──> web app :3000 (Next.js)
   └──────> API :8000 (FastAPI) ──> Postgres (db) <── worker (reads documents)
                                 ──> S3 bucket       (documents)
                                 ──> SMTP server     (invitations, resets)
                                 ──> AI provider     (optional)
```

## 1. What you need

- A Linux server with Docker Engine 24+ and the Compose plugin
  (2 vCPU / 4 GB RAM is enough to start; OCR is the heaviest thing it does).
- A domain with HTTPS in front of the containers: a reverse proxy
  (Caddy, nginx, Traefik) or a cloud load balancer. The containers serve
  plain HTTP and must not be exposed to the internet without it.
- A private S3 bucket (section 3).
- An SMTP account for outgoing mail: Google Workspace, Zoho, Brevo,
  AWS SES and so on.

## 2. Configure

```bash
git clone https://github.com/AI-MayankSaraf/inventoryai.git
cd inventoryai
cp .env.example .env
```

Fill in every value in the "required" block of `.env`. Generate each secret
and password separately:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

Set the public addresses, for example with the web app on
`https://app.example.com` and the API on `https://api.example.com`:

```dotenv
PUBLIC_WEB_URL=https://app.example.com
PUBLIC_API_URL=https://api.example.com
FORWARDED_ALLOW_IPS=<your proxy's address, as the API container sees it>
```

`PUBLIC_API_URL` is compiled into the web app, so rebuild the frontend
image whenever it changes (`docker compose build frontend`).

With `ENVIRONMENT=production` the API **refuses to start** when
`JWT_SECRET` or `SECRETS_KEY` is missing, short (under 32 characters) or the
same as the other, or when `DEBUG` is on. The error names what to fix.

Keep `SECRETS_KEY` safe and never change it casually: it encrypts SMTP
passwords saved under Settings → Email, and those become unreadable if it
changes.

## 3. The S3 bucket

Create a bucket in the region closest to your users (for India,
`ap-south-1`) with:

- **Block all public access: on.** The storage check refuses a public bucket.
- **Default encryption:** SSE-S3 (AES256), or SSE-KMS with `S3_SSE=aws:kms`
  and `S3_KMS_KEY_ID`.
- Versioning: recommended.

Give the server access with an IAM role (EC2 instance profile, ECS task
role) rather than keys. The role needs exactly:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:ListBucket", "s3:GetBucketPublicAccessBlock"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET" },
    { "Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"],
      "Resource": "arn:aws:s3:::YOUR-BUCKET/*" }
  ]
}
```

With a role, leave `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` blank. If
the server is not on AWS, create an IAM user with the same policy and put
its keys in `.env`.

### Prove the bucket before going live

```bash
docker compose build
docker compose run --rm --no-deps migrate python -m scripts.verify_s3
```

It checks, against the real bucket, that the bucket is not public, that
objects are encrypted, and that download links carry the right headers,
work, and **expire**. Local emulators accept expired or tampered links, so
this is the only place that last part can be proven. It must end with
`0 failed` and must not print the "non-AWS endpoint" warning. Everything it
writes goes under `co/_verify/` and is deleted again.

## 4. Start

```bash
docker compose up -d --build
docker compose ps          # db healthy, migrate exited 0, backend healthy, worker running
curl http://localhost:8000/health
```

`migrate` applies database migrations and the reference data (units,
permissions, roles, plans) on every `up`, then exits; the API starts after
it succeeds.

Create the platform admin once. Set `PLATFORM_ADMIN_PASSWORD` in `.env`
(8+ characters, a letter and a digit), then:

```bash
docker compose run --rm migrate python -m app.db.seed --admin-email you@example.com --admin-name "Your Name"
```

Clear `PLATFORM_ADMIN_PASSWORD` from `.env` again afterwards. Sign in at
`PUBLIC_WEB_URL`, open **System Admin → Onboard Company**, and create the
first company. Its owner receives an email invitation.

Never run `python -m app.db.seed --demo` on a server others can reach: the
demo accounts have published passwords.

### The document worker

An upload returns as soon as the file is stored; the `worker` container
reads it (parsing, OCR, matching) from a queue kept in Postgres, and the
review screen shows its progress. Nothing else is needed for the queue.

- More throughput: `docker compose up -d --scale worker=3`. Workers never
  take the same document.
- A worker that dies mid-document (a crash, a deploy) is noticed after
  `WORKER_STALE_AFTER_MINUTES` (15) and the document is read again, up to
  `WORKER_MAX_RETRIES` (3) times; after that it is marked failed with a
  reason, and a person can press Retry. A file that simply cannot be read
  fails once, with the reason, and is not retried by itself.
- Without Docker, the API runs a worker inside its own process by default
  (`EXTRACTION_WORKER=embedded`), so a single `uvicorn` is a complete install.
  Set `EXTRACTION_WORKER=external` and run `python -m app.worker` to separate them.

## 5. Reverse proxy

Example Caddyfile (Caddy obtains the HTTPS certificates itself):

```text
app.example.com {
    reverse_proxy localhost:3000
}
api.example.com {
    reverse_proxy localhost:8000
    request_body {
        max_size 25MB
    }
}
```

Uploads are capped at 20 MB, so allow a little more at the proxy. Once
the proxy is in place, bind the container ports to localhost only
(`127.0.0.1:8000:8000` in `docker-compose.yml`) so nothing bypasses it.

## 6. Sign-in rate limits

Failed sign-ins, password-reset requests and bad reset links are limited
per client address, on top of the five-failure account lockout. Defaults
and format are in `backend/.env.example` (`RATE_LIMIT_*`). Two things
matter in production:

- The API must see each user's real address. That is what
  `FORWARDED_ALLOW_IPS` is for. If it is wrong, every user shares the
  proxy's counter and one person's typos can lock out an office.
- The counters live in the API process's memory. The image runs one
  process (`WEB_CONCURRENCY=1`). If you run several processes or replicas,
  each counts separately, so add a limit at the load balancer or WAF as well.

## 7. Operations

### Upgrade

```bash
git pull
docker compose up -d --build     # migrate runs before the new API starts
```

### Back up the database

Documents are in S3, which versioning protects. The database:

```bash
docker compose exec db pg_dump -U inventoryai -Fc inventoryai > inventoryai-$(date +%F).dump
```

Restore into a fresh volume with `pg_restore -U inventoryai -d inventoryai --clean`.
Test a restore before you need one.

### Logs

```bash
docker compose logs -f backend worker
```

## 8. Everything on one machine (trial, CI)

`docker-compose.local.yml` adds a local S3 stand-in (Floci) and a mail
catcher (Mailpit, inbox at <http://localhost:8025>) and points the API at them:

```bash
cp .env.example .env     # fill in the five secrets; S3_BUCKET=inventoryai-documents
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Nothing sent from this setup leaves the machine, and files live in a Docker
volume. Use it for trials, never for real data.

## 9. Optional: AI provider

Matching by meaning, reading unusual column headings, and the assistant's
suggestions use an AI provider. Without one (`AI_PROVIDER=none`), exact and
text-similarity matching still work and everything else goes to a person.

- **Ollama on the Docker host:** `AI_PROVIDER=ollama`,
  `AI_BASE_URL=http://host.docker.internal:11434` (on Linux also add
  `extra_hosts: ["host.docker.internal:host-gateway"]` to `backend`),
  `AI_MODEL_SMALL=llama3.2:latest`, `AI_EMBEDDING_MODEL=nomic-embed-text`,
  `AI_EMBEDDING_DIMENSIONS=768`.
- **A hosted OpenAI-compatible API:** `AI_PROVIDER=openai`, its
  `AI_BASE_URL` and `AI_API_KEY`, and its model names. Documents' text is sent
  to that provider, so check that your customers' data may go there.
