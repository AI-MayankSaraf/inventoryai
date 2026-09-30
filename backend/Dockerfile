# InventoryAI API. Also used, with a different command, for migrations and
# seeding (see docker-compose.yml, service `migrate`).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Tesseract reads scanned quotations (OCR_PROVIDER=tesseract); English and
# Hindi, matching the default OCR_LANGUAGES of eng+hin.
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin curl \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY alembic.ini .
COPY alembic ./alembic
COPY app ./app
COPY scripts ./scripts

RUN useradd --system --uid 10001 --home /app inventoryai
USER inventoryai

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=30s --retries=5 \
  CMD curl -fsS http://127.0.0.1:8000/health || exit 1

# --proxy-headers + FORWARDED_ALLOW_IPS: behind a reverse proxy the client
# address comes from X-Forwarded-For, which the sign-in rate limits need.
# Set FORWARDED_ALLOW_IPS to your proxy's address; "*" trusts any sender and
# is only safe when nothing but the proxy can reach this port.
ENV FORWARDED_ALLOW_IPS=127.0.0.1 WEB_CONCURRENCY=1
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"$FORWARDED_ALLOW_IPS\" --workers \"$WEB_CONCURRENCY\""]
