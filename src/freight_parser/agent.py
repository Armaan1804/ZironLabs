"""
agent.py — Orchestration layer that wires extraction → validation → decision.

This module is the single entry-point for programmatic use of the pipeline.
It has no I/O of its own: it reads nothing from disk, prints nothing, and
raises no unhandled exceptions — every failure path is encoded as a
FLAGGED_FOR_HUMAN_REVIEW decision so callers always get a typed result.

Data flow
---------
raw_text (str)
    │
    ├─► extract_document()  →  FreightDocument  (or ExtractionError)
    │
    └─► validate()          →  ValidationResult
                                    │
                                    └─► AgentDecision
"""

from __future__ import annotations

import logging

from freight_parser.errors import ExtractionError
from freight_parser.extractor import extract_document
from freight_parser.schemas import AgentDecision, DecisionStatus, ValidationIssue
from freight_parser.validator import validate

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def process_document(raw_text: str) -> AgentDecision:
    """Run the full pipeline on *raw_text* and return an :class:`AgentDecision`.

    This function never raises.  Every failure — including LLM errors and
    exhausted retries — is returned as a ``FLAGGED_FOR_HUMAN_REVIEW`` decision
    so the CLI and any calling code always receive a typed result.

    Parameters
    ----------
    raw_text:
        Normalised plain-text freight document, as produced by
        :mod:`freight_parser.ingest`.

    Returns
    -------
    AgentDecision
        ``status`` is ``APPROVED`` only when extraction succeeds and there are
        zero errors *and* zero warnings.  All other outcomes yield
        ``FLAGGED_FOR_HUMAN_REVIEW``.
    """
    # ── Stage 1: LLM extraction ─────────────────────────────────────────────
    try:
        doc = extract_document(raw_text)
    except ExtractionError as exc:
        log.error("Extraction failed: %s", exc)
        return _extraction_failure_decision(str(exc))

    log.debug("Extraction succeeded; running validator.")

    # ── Stage 2: deterministic validation ───────────────────────────────────
    result = validate(doc)

    log.info(
        "Validation: %d error(s), %d warning(s).",
        len(result.errors),
        len(result.warnings),
    )

    # ── Stage 3: decision ────────────────────────────────────────────────────
    if result.is_clean:
        return _approved_decision(doc)

    return _flagged_decision(doc, result.issues)


# ---------------------------------------------------------------------------
# Private decision builders
# ---------------------------------------------------------------------------


def _approved_decision(doc) -> AgentDecision:
    """Build an APPROVED decision for a document with no issues."""
    return AgentDecision(
        status=DecisionStatus.APPROVED,
        summary=(
            "Document passed all validation checks. "
            "Carrier, load number, locations, rates, and weight are complete and consistent."
        ),
        data=doc,
        issues=[],
    )


def _flagged_decision(doc, issues: list[ValidationIssue]) -> AgentDecision:
    """Build a FLAGGED_FOR_HUMAN_REVIEW decision, listing every issue."""
    error_count = sum(1 for i in issues if i.severity.value == "ERROR")
    warning_count = sum(1 for i in issues if i.severity.value == "WARNING")

    # ── Count line ───────────────────────────────────────────────────────────
    parts: list[str] = []
    if error_count:
        parts.append(f"{error_count} error{'s' if error_count != 1 else ''}")
    if warning_count:
        parts.append(f"{warning_count} warning{'s' if warning_count != 1 else ''}")
    count_line = "Flagged: " + ", ".join(parts) + "."

    # ── Per-issue lines ──────────────────────────────────────────────────────
    issue_lines = [
        f"[{i.severity.value}] {i.code.value}: {i.message}"
        for i in issues
    ]

    summary = " ".join([count_line] + issue_lines)

    return AgentDecision(
        status=DecisionStatus.FLAGGED_FOR_HUMAN_REVIEW,
        summary=summary,
        data=doc,
        issues=issues,
    )


def _extraction_failure_decision(error_message: str) -> AgentDecision:
    """Build a FLAGGED decision when extraction itself failed (no doc available)."""
    return AgentDecision(
        status=DecisionStatus.FLAGGED_FOR_HUMAN_REVIEW,
        summary=f"Extraction failed — could not parse document with LLM. Error: {error_message}",
        data=None,
        issues=[],
    )
