"""
extractor.py — LLM extraction layer for the freight_parser pipeline.

This is the ONLY module that communicates with the LLM. It must not import
ingest.py or touch the filesystem.

How strict JSON is guaranteed
------------------------------
1. **Schema as tool definition** — ``instructor`` serialises the
   ``FreightDocument`` Pydantic model into a JSON-schema and passes it to the
   Groq API as a structured-output constraint. The model is therefore
   *constrained* to emit JSON that matches the shape, not just asked to
   do so in prose.

2. **Pydantic validation** — ``instructor`` deserialises the raw JSON into a
   ``FreightDocument`` instance, running all Pydantic field validators (type
   coercions, regex checks, etc.) in the process.

3. **Retry loop** — If Pydantic raises a ``ValidationError`` (e.g. the model
   emitted a string where a float was expected *after* coercion failed), the
   error message is automatically appended to the conversation and the model
   is re-prompted.  This loop repeats up to ``max_retries`` times before
   ``instructor`` raises ``InstructorRetryException``, which we catch and
   re-raise as :class:`~freight_parser.errors.ExtractionError`.

Data flow
---------
raw text (str) ──► build_client() ──► extract_document() ──► FreightDocument
"""

from __future__ import annotations

import logging
import time
from typing import Any

import instructor
from groq import Groq

from freight_parser.config import AppConfig, get_config
from freight_parser.errors import ExtractionError
from freight_parser.schemas import FreightDocument

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT: str = """
You are a freight-document data-extraction engine. Your sole job is to read the
provided freight or rate-confirmation document and return a single JSON object
that conforms exactly to the supplied schema.

CRITICAL RULES — follow every rule without exception:

1. EXTRACT, NEVER INVENT
   Return null for any field that is missing from the document or genuinely
   ambiguous. Do not guess, infer, default, or hallucinate values. If you are
   not certain a value is present, return null.

2. NEVER CORRECT OR RECOMPUTE NUMBERS
   Copy linehaul rate, fuel surcharge, and total pay EXACTLY as they appear in
   the document — even if they do not add up correctly. A dedicated validator
   checks arithmetic downstream. Silently "fixing" a discrepancy destroys the
   audit trail and defeats the purpose of validation.

3. LOAD / REFERENCE NUMBER LABELS
   The load number may appear under any of these labels (case-insensitive):
   "Ref #", "Reference #", "Reference", "Load #", "Load Number",
   "PRO #", "PRO Number", "Order #", "Order Number", "Confirmation #".
   Extract whichever value follows the matching label.

4. LOCATIONS — FACILITY NAMES ARE NOT CITIES
   The `facility_name` field holds the name of the building or site
   (e.g. "Distribution Center 4", "Warehouse B"). The `city` field holds
   only the city name (e.g. "Dallas"). Never put a facility name into the
   `city` field. When an address appears as "Facility, City, ST ZIP", split
   it accordingly: facility_name="Facility", city="City", state="ST",
   zip_code="ZIP". For state, always use the two-letter abbreviation in
   uppercase (e.g. "TX", not "Texas"). If there are multiple stops, use
   the FIRST pickup as `pickup_location` and the FINAL delivery as
   `delivery_location`.

5. NUMERIC FORMATTING
   - Monetary amounts: strip currency symbols ($, USD) and thousands
     separators (,) and return a plain decimal number (e.g. 2200.00).
   - Weight: strip units ("lbs", "lb", "pounds") and thousands separators
     and return a plain integer (e.g. 46800).

6. IGNORE IRRELEVANT CONTENT
   Do not extract: boilerplate legal text, signature blocks, terms and
   conditions, special instructions, carrier agreement clauses, or
   page headers/footers. Focus exclusively on the structured data fields
   defined in the schema.
""".strip()


# ---------------------------------------------------------------------------
# Client factory
# ---------------------------------------------------------------------------


def build_client(cfg: AppConfig | None = None) -> Any:
    """Construct and return an ``instructor``-patched Groq client.

    Parameters
    ----------
    cfg:
        Application config.  If *None*, :func:`~freight_parser.config.get_config`
        is called automatically.

    Returns
    -------
    instructor.Instructor
        A patched ``Groq`` configured for the Groq provider.
        Accepts ``response_model`` in ``chat.completions.create()`` calls.

    Raises
    ------
    ConfigError
        Propagated from :func:`~freight_parser.config.get_config` when the
        API key is absent or invalid.
    """
    if cfg is None:
        cfg = get_config()

    raw_client = Groq(api_key=cfg.api_key)
    # Patch the Groq client to support response_model
    patched = instructor.from_groq(
        raw_client,
        mode=instructor.Mode.JSON,
    )
    log.debug("Instructor-patched Groq client created (model=%s).", cfg.model_name)
    return patched


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------


def extract_document(
    raw_text: str,
    client: Any = None,
    cfg: AppConfig | None = None,
) -> FreightDocument:
    """Parse *raw_text* into a :class:`~freight_parser.schemas.FreightDocument`.

    Uses ``instructor`` to call the Groq API with the ``FreightDocument``
    schema enforced as a structured-output constraint.  If the model returns
    malformed JSON or a Pydantic validation error occurs, ``instructor``
    automatically re-prompts the model (up to ``cfg.max_retries`` attempts)
    with the validation error message appended, giving the model a chance to
    self-correct.

    Parameters
    ----------
    raw_text:
        Normalised plain-text content of the freight document, as produced by
        :mod:`freight_parser.ingest`.
    client:
        Pre-built instructor-patched client.  When *None*, :func:`build_client`
        is called automatically.  Inject a mock here in tests to avoid real
        API calls.
    cfg:
        Application config.  When *None*, :func:`~freight_parser.config.get_config`
        is called automatically.  Used for ``model_name`` and ``max_retries``.

    Returns
    -------
    FreightDocument
        Pydantic model populated with values extracted from the document.
        Fields the model could not find will be *None*.

    Raises
    ------
    ExtractionError
        * If *raw_text* is empty or contains only whitespace.
        * If the Groq API call fails (network error, quota exceeded, etc.).
        * If ``instructor`` exhausts all retries without a valid response.
    """
    # --- Guard: reject empty input before touching the API -----------------
    if not raw_text or not raw_text.strip():
        raise ExtractionError(
            "Cannot extract from empty input. "
            "Ensure the document was ingested correctly before calling extract_document()."
        )

    # --- Resolve config & client lazily ------------------------------------
    if cfg is None:
        cfg = get_config()

    if client is None:
        client = build_client(cfg)

    log.info(
        "Sending document to LLM (model=%s, max_retries=%d, ~%d chars).",
        cfg.model_name,
        cfg.max_retries,
        len(raw_text),
    )

    # --- Call the LLM via instructor with HTTP 503/429 backoff -----------------
    # instructor's max_retries handles Pydantic *validation* retries (i.e. model
    # returned parseable JSON but it violated the schema).  Transient HTTP 503
    # or 429 errors require a separate retry layer with backoff.
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",   "content": raw_text},
    ]
    http_attempts = 3
    last_exc: Exception | None = None
    for attempt in range(1, http_attempts + 1):
        try:
            doc: FreightDocument = client.chat.completions.create(
                model=cfg.model_name,
                response_model=FreightDocument,
                messages=messages,
                max_retries=cfg.max_retries,
                temperature=0.0,
            )
            break  # success — exit retry loop
        except Exception as exc:
            exc_str = str(exc)
            # 503 / 429 are transient: back off and retry
            if any(code in exc_str for code in ("503", "429", "UNAVAILABLE", "RESOURCE_EXHAUSTED", "rate_limit_exceeded")):
                last_exc = exc
                if attempt < http_attempts:
                    wait = 2 ** attempt  # 2s, 4s
                    log.warning(
                        "LLM HTTP %s on attempt %d/%d — retrying in %ds.",
                        "503" if "503" in exc_str else "429",
                        attempt, http_attempts, wait,
                    )
                    time.sleep(wait)
                    continue
                # Exhausted HTTP retries
                raise ExtractionError(
                    f"LLM failed to return a valid FreightDocument after "
                    f"{cfg.max_retries} attempt(s). "
                    "The document may be too ambiguous or the model is misbehaving. "
                    f"Last error: {exc}"
                ) from exc
            # Non-transient error — classify and raise immediately
            if any(
                kw in exc_str.lower()
                for kw in ("api key", "permission", "403", "401", "quota", "invalid_api_key")
            ):
                raise ExtractionError(
                    f"Groq API authentication or quota error: {exc}. "
                    "Check your GROQ_API_KEY and API quota."
                ) from exc
            exc_type = type(exc).__name__
            if "retry" in exc_type.lower() or "retries" in exc_str.lower():
                raise ExtractionError(
                    f"LLM failed to return a valid FreightDocument after "
                    f"{cfg.max_retries} attempt(s). "
                    "The document may be too ambiguous or the model is misbehaving. "
                    f"Last error: {exc}"
                ) from exc
            raise ExtractionError(
                f"Groq API call failed ({exc_type}): {exc}."
            ) from exc
    else:
        # Should only be reached if http_attempts == 0 (defensive)
        raise ExtractionError("No HTTP attempts were made.")

    log.info(
        "Extraction successful: carrier=%r load_number=%r weight_lbs=%r",
        doc.carrier_name,
        doc.load_number,
        doc.weight_lbs,
    )
    return doc
