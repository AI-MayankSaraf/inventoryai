"""
The seam between the deterministic pipeline and a hosted model.

Rungs 1–5 of the match ladder (exact SKU, supplier alias, barcode,
normalisation rules, trigram) are arithmetic and SQL: they cost nothing,
they are reproducible, and they run here. Rungs 6–7 (embeddings, an LLM)
and OCR for scanned images need a provider, and this installation has
none configured.

That is a *state*, not a failure. `08_AI_DATA_MODEL.md` §4.3 already says
embedding and LLM matches are never auto-accepted — they only ever produce
a suggestion for a human to confirm. So with no provider the pipeline loses
suggestions, never correctness: a line the deterministic rungs cannot settle
goes to review, which is exactly where an unconfirmed embedding match would
have sent it anyway.

What this module refuses to do is pretend. There is no "simulated" provider
that invents a confidence score, because a fabricated 0.86 is worse than an
honest "a person needs to look at this" — it would teach the reviewer to
trust a number that means nothing. `describe()` is what the UI renders, so
the screen can say which rungs actually ran.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from app.core.config import get_settings

log = logging.getLogger(__name__)

_SUPPORTED = {"ollama", "openai"}
_DEFAULT_URL = {"ollama": "http://localhost:11434", "openai": "https://api.openai.com"}

#: After a connection failure the provider is treated as down for this long,
#: so one stopped Ollama doesn't add a timeout to every file in a batch.
_COOLDOWN_SECONDS = 60.0


class ProviderNotConfigured(RuntimeError):
    """Raised by a provider that has no credentials.

    Callers inside the pipeline catch this and record the rung as skipped;
    it is never allowed to fail a document, because every rung above it is
    optional by design.
    """

    def __init__(self, kind: str, setting: str) -> None:
        super().__init__(
            f"No {kind} provider is configured. Set {setting} to enable this step; "
            f"until then the pipeline stops at the deterministic rungs and asks a person."
        )
        self.kind = kind
        self.setting = setting


class ProviderError(RuntimeError):
    """The provider is configured but the call failed — unreachable, timed
    out, or answered with something unusable. Callers fall back exactly as
    they would with no provider; the message goes to the log and the trace."""


@dataclass(frozen=True)
class ProviderStatus:
    kind: str
    configured: bool
    provider: str
    model_id: Optional[str]
    note: str


class _Http:
    """Blocking JSON-over-HTTP, run on a worker thread so a slow model never
    stalls the event loop. Stdlib only — no client library to pin."""

    _down_until: float = 0.0

    @classmethod
    async def post(cls, url: str, body: dict, *, api_key: str = "", timeout: float) -> dict:
        if time.monotonic() < cls._down_until:
            raise ProviderError("The AI provider was unreachable a moment ago; not retrying yet")

        def call() -> dict:
            headers = {"content-type": "application/json"}
            if api_key:
                headers["authorization"] = f"Bearer {api_key}"
            request = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read())

        try:
            return await asyncio.to_thread(call)
        except urllib.error.HTTPError as exc:
            detail = exc.read()[:300].decode(errors="replace")
            raise ProviderError(f"AI provider answered {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            cls._down_until = time.monotonic() + _COOLDOWN_SECONDS
            raise ProviderError(f"AI provider unreachable at {url}: {exc}") from exc
        except ValueError as exc:
            raise ProviderError("AI provider sent a response that is not JSON") from exc


def _base_url() -> str:
    s = get_settings()
    return (s.ai_base_url or _DEFAULT_URL.get(s.ai_provider, "")).rstrip("/")


def _provider_ready() -> bool:
    s = get_settings()
    if s.ai_provider not in _SUPPORTED:
        return False
    # A local Ollama needs no key; a hosted API always does.
    return s.ai_provider == "ollama" or bool(s.ai_api_key)


class EmbeddingProvider:
    """Turns text into vectors: product matching by meaning (rung 6,
    `embedding_service.py` / `variant_embeddings`) and reading unusual
    spreadsheet headings (`column_assist.py`)."""

    kind = "embedding"
    _warned_dimensions = False

    @property
    def configured(self) -> bool:
        return _provider_ready() and bool(get_settings().ai_embedding_model)

    async def embed(self, texts: list[str], *, role: str = "document") -> list[list[float]]:
        """`role` is `query` or `document`. Some models (nomic) are trained
        with a task prefix and lose much of their accuracy without it."""
        if not self.configured:
            raise ProviderNotConfigured("embedding", "AI_PROVIDER / AI_EMBEDDING_MODEL")
        if not texts:
            return []
        s = get_settings()
        model = s.ai_embedding_model
        if "nomic" in model.lower():
            texts = [f"search_{role}: {t}" for t in texts]
        if s.ai_provider == "ollama":
            out = await _Http.post(
                f"{_base_url()}/api/embed", {"model": model, "input": texts}, timeout=s.ai_timeout_seconds
            )
            vectors = out.get("embeddings")
        else:
            out = await _Http.post(
                f"{_base_url()}/v1/embeddings",
                {"model": model, "input": texts},
                api_key=s.ai_api_key,
                timeout=s.ai_timeout_seconds,
            )
            vectors = [d.get("embedding") for d in sorted(out.get("data", []), key=lambda d: d.get("index", 0))]
        if not isinstance(vectors, list) or len(vectors) != len(texts) or not all(vectors):
            raise ProviderError("The embedding model returned the wrong number of vectors")
        expected = s.ai_embedding_dimensions
        if expected and len(vectors[0]) != expected and not EmbeddingProvider._warned_dimensions:
            EmbeddingProvider._warned_dimensions = True
            log.warning(
                "Embedding model %s returns %d dimensions, AI_EMBEDDING_DIMENSIONS says %d",
                model, len(vectors[0]), expected,
            )
        return vectors

    def status(self) -> ProviderStatus:
        s = get_settings()
        return ProviderStatus(
            kind=self.kind,
            configured=self.configured,
            provider=s.ai_provider,
            model_id=s.ai_embedding_model or None,
            note=(
                "Products are also matched by meaning (suggestions only — a person confirms). "
                "Unusual column headings are read by meaning too."
                if self.configured
                else "Semantic matching is off — lines the deterministic rungs cannot settle go to review."
            ),
        )


class LlmProvider:
    """A language model, asked for small structured answers only.

    Note what a prompt carries, per §7: the header row plus a few sample
    rows — never a whole file and never the whole catalogue. That bound is
    part of the design, not an optimisation. Every answer is validated by
    the caller against the data before it is shown, and it is only ever a
    suggestion a person confirms.
    """

    kind = "llm"

    @property
    def configured(self) -> bool:
        return _provider_ready() and bool(get_settings().ai_model_small)

    async def complete_json(self, system: str, user: str, schema: dict) -> dict:
        if not self.configured:
            raise ProviderNotConfigured("language model", "AI_PROVIDER / AI_MODEL_SMALL")
        s = get_settings()
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if s.ai_provider == "ollama":
            out = await _Http.post(
                f"{_base_url()}/api/chat",
                {
                    "model": s.ai_model_small,
                    "messages": messages,
                    "stream": False,
                    "format": schema,
                    "options": {"temperature": 0, "seed": 7},
                },
                timeout=s.ai_timeout_seconds,
            )
            content = (out.get("message") or {}).get("content", "")
        else:
            out = await _Http.post(
                f"{_base_url()}/v1/chat/completions",
                {
                    "model": s.ai_model_small,
                    "messages": messages,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                },
                api_key=s.ai_api_key,
                timeout=s.ai_timeout_seconds,
            )
            content = ((out.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        try:
            parsed = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise ProviderError("The language model did not answer with JSON") from exc
        if not isinstance(parsed, dict):
            raise ProviderError("The language model answered with something other than an object")
        return parsed

    def status(self) -> ProviderStatus:
        s = get_settings()
        return ProviderStatus(
            kind=self.kind,
            configured=self.configured,
            provider=s.ai_provider,
            model_id=s.ai_model_small or None,
            note=(
                "The language model helps only with spreadsheet columns nothing else could place, and its "
                "answer is checked against the data. It is not run per line: too slow for that on a local model."
                if self.configured
                else "Column mappings are proposed by header synonyms; anything unmatched is left for you to map."
            ),
        )


class OcrProvider:
    """Scanned images and image-only PDFs.

    Without this, a .jpg/.png upload fails with a readable reason rather
    than producing an empty extraction that looks like the document was
    blank.
    """

    kind = "ocr"
    _checked: tuple[float, bool, str] = (0.0, False, "")

    def _check(self) -> tuple[bool, str]:
        """Whether Tesseract really runs — cached for a minute, since
        asking means starting the binary."""
        from app.modules.ai import ocr

        at, ok, why = OcrProvider._checked
        if time.monotonic() - at > 60:
            ok, why = ocr.available()
            OcrProvider._checked = (time.monotonic(), ok, why)
        return ok, why

    @property
    def configured(self) -> bool:
        return get_settings().ocr_provider != "none" and self._check()[0]

    def read_document(self, blob: bytes, mime_type: str, hints=None) -> tuple[str, list]:
        """(text, [(sheet name, grid)]). Blocking — call from a worker thread."""
        from app.modules.ai import ocr

        if not self.configured:
            raise ProviderNotConfigured("OCR", "OCR_PROVIDER")
        try:
            return ocr.read(blob, mime_type, hints)
        except ocr.OcrUnavailable as exc:
            raise ProviderError(str(exc)) from exc
        except Exception as exc:  # a Tesseract failure is a failed read, not a crash
            log.warning("OCR failed: %s", exc)
            raise ProviderError("The scan could not be read by OCR. Try a clearer scan, or upload the spreadsheet.") from exc

    def read(self, blob: bytes, mime_type: str) -> str:
        return self.read_document(blob, mime_type)[0]

    def status(self) -> ProviderStatus:
        s = get_settings()
        configured = self.configured
        why = "" if configured or s.ocr_provider == "none" else f" ({self._check()[1]})"
        return ProviderStatus(
            kind=self.kind,
            configured=configured,
            provider=s.ocr_provider,
            model_id=s.ocr_languages if configured else None,
            note=(
                "Scanned images and image-only PDFs are read by OCR; check the values against the page."
                if configured
                else "Scanned images cannot be read — upload the spreadsheet or a text PDF instead." + why
            ),
        )


embeddings = EmbeddingProvider()
llm = LlmProvider()
ocr = OcrProvider()


def all_statuses() -> list[ProviderStatus]:
    return [embeddings.status(), llm.status(), ocr.status()]
