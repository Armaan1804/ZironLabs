"""
validator.py — Deterministic business-rule validation for freight documents.

This module is a **pure function layer**: no LLM calls, no file I/O, no side
effects.  Every function here is trivially unit-testable with plain
``FreightDocument`` fixtures — no mocks required.

Rules implemented
-----------------
1. INCOMPLETE_DATA (ERROR)  — one issue per missing/blank required field.
2. RATE_MISMATCH  (ERROR)   — linehaul + fuel_surcharge ≠ total_pay.
3. OVERWEIGHT_LOAD (WARNING) — weight_lbs > MAX_WEIGHT_LBS (45 000).

Skipping behaviour
------------------
If the inputs required for a rule are themselves missing (None / blank), that
rule is skipped — the missing-field issues already reported by rule 1 are
sufficient signal.  There is no value in compounding a missing-field error
with a downstream arithmetic error.
"""

from __future__ import annotations

import logging
import math
from decimal import Decimal

from freight_parser.schemas import (
    FreightDocument,
    IssueCode,
    Location,
    Severity,
    ValidationIssue,
    ValidationResult,
)

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Legal / contractual weight ceiling in pounds.  Loads exceeding this value
#: receive an OVERWEIGHT_LOAD WARNING.  Exactly 45 000 lbs is permissible.
MAX_WEIGHT_LBS: int = 45_000

#: Absolute tolerance (in dollars) used when comparing floating-point rate
#: values.  Values within $0.01 of each other are considered equal to avoid
#: IEEE 754 noise false-flagging a valid document.
#: We convert to Decimal for the comparison, but this constant documents intent.
_RATE_ABS_TOLERANCE: float = 0.01


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate(doc: FreightDocument) -> ValidationResult:
    """Run all business rules against *doc* and return a :class:`ValidationResult`.

    Parameters
    ----------
    doc:
        Extracted freight document, as produced by
        :mod:`freight_parser.extractor`.  Fields may be *None* when the LLM
        could not find them in the source document.

    Returns
    -------
    ValidationResult
        Aggregated list of :class:`~freight_parser.schemas.ValidationIssue`
        objects.  An empty list means the document is clean.
    """
    issues: list[ValidationIssue] = []

    # Rule 1 — collect all missing-field issues first so downstream rules can
    # inspect which fields are present before deciding whether to run.
    issues.extend(_check_incomplete_data(doc))

    # Determine which fields are actually present (not None / blank) so rules
    # 2 and 3 can skip cleanly when inputs are missing.
    rates_present = _rates_are_present(doc)
    weight_present = doc.weight_lbs is not None

    # Rule 2 — rate arithmetic
    if rates_present:
        issues.extend(_check_rate_mismatch(doc))

    # Rule 3 — weight ceiling
    if weight_present:
        issues.extend(_check_overweight(doc))

    log.debug(
        "Validation complete: %d issue(s) (%d error(s), %d warning(s)).",
        len(issues),
        sum(1 for i in issues if i.severity == Severity.ERROR),
        sum(1 for i in issues if i.severity == Severity.WARNING),
    )
    return ValidationResult(issues=issues)


# ---------------------------------------------------------------------------
# Rule 1 — INCOMPLETE_DATA
# ---------------------------------------------------------------------------

#: Mapping of (human-readable label, field path expression) for every required
#: scalar field.  The field path is the string placed in ValidationIssue.fields.
_REQUIRED_SCALAR_FIELDS: list[tuple[str, str]] = [
    ("carrier_name", "carrier_name"),
    ("load_number", "load_number"),
    ("total_linehaul_rate", "total_linehaul_rate"),
    ("fuel_surcharge", "fuel_surcharge"),
    ("total_pay", "total_pay"),
    ("weight_lbs", "weight_lbs"),
]

#: Required sub-fields within pickup_location and delivery_location.
_REQUIRED_LOCATION_SUBFIELDS: list[tuple[str, str]] = [
    ("city", "city"),
    ("state", "state"),
    ("zip_code", "zip_code"),
]


def _check_incomplete_data(doc: FreightDocument) -> list[ValidationIssue]:
    """Emit one INCOMPLETE_DATA ERROR per missing or blank required field.

    Checks top-level scalar fields first, then the required sub-fields of
    ``pickup_location`` and ``delivery_location``.
    """
    issues: list[ValidationIssue] = []

    # ── Top-level scalar fields ──────────────────────────────────────────────
    for label, field_path in _REQUIRED_SCALAR_FIELDS:
        value = getattr(doc, label, None)
        if _is_blank(value):
            issues.append(_missing_field_issue(label, field_path))

    # ── Location sub-fields ──────────────────────────────────────────────────
    for loc_attr, loc_label in (
        ("pickup_location", "pickup"),
        ("delivery_location", "delivery"),
    ):
        loc: Location | None = getattr(doc, loc_attr, None)
        if loc is None:
            # Entire location block is missing — report each sub-field
            for sub_label, _ in _REQUIRED_LOCATION_SUBFIELDS:
                field_path = f"{loc_attr}.{sub_label}"
                issues.append(_missing_field_issue(
                    f"{loc_label} {sub_label}",
                    field_path,
                ))
        else:
            for sub_label, sub_field in _REQUIRED_LOCATION_SUBFIELDS:
                value = getattr(loc, sub_label, None)
                if _is_blank(value):
                    field_path = f"{loc_attr}.{sub_label}"
                    issues.append(_missing_field_issue(
                        f"{loc_label} {sub_label}",
                        field_path,
                    ))

    return issues


def _missing_field_issue(human_label: str, field_path: str) -> ValidationIssue:
    """Return a single INCOMPLETE_DATA ValidationIssue for *field_path*."""
    return ValidationIssue(
        code=IssueCode.INCOMPLETE_DATA,
        severity=Severity.ERROR,
        message=f"Required field '{human_label}' is missing or blank.",
        fields=[field_path],
    )


# ---------------------------------------------------------------------------
# Rule 2 — RATE_MISMATCH
# ---------------------------------------------------------------------------


def _check_rate_mismatch(doc: FreightDocument) -> list[ValidationIssue]:
    """Return a RATE_MISMATCH ERROR if linehaul + fuel_surcharge ≠ total_pay.

    Uses :class:`decimal.Decimal` arithmetic to avoid IEEE 754 floating-point
    drift (e.g. 0.1 + 0.2 ≠ 0.3 in float arithmetic).  Two totals are
    considered equal when they differ by less than $0.01.

    Precondition: caller guarantees all three rate fields are non-None.
    """
    linehaul = Decimal(str(doc.total_linehaul_rate))
    fuel = Decimal(str(doc.fuel_surcharge))
    total = Decimal(str(doc.total_pay))

    computed = linehaul + fuel
    difference = abs(total - computed)

    # Tolerance: $0.01 covers legitimate rounding differences in invoices.
    if difference <= Decimal("0.01"):
        return []

    return [
        ValidationIssue(
            code=IssueCode.RATE_MISMATCH,
            severity=Severity.ERROR,
            message=(
                f"{linehaul:.2f} + {fuel:.2f} = {computed:.2f}, "
                f"but total_pay is {total:.2f} "
                f"(difference {difference:.2f})."
            ),
            fields=["total_linehaul_rate", "fuel_surcharge", "total_pay"],
        )
    ]


# ---------------------------------------------------------------------------
# Rule 3 — OVERWEIGHT_LOAD
# ---------------------------------------------------------------------------


def _check_overweight(doc: FreightDocument) -> list[ValidationIssue]:
    """Return an OVERWEIGHT_LOAD WARNING if weight_lbs > MAX_WEIGHT_LBS.

    Exactly :data:`MAX_WEIGHT_LBS` lbs is within the limit and must NOT flag.

    Precondition: caller guarantees weight_lbs is non-None.
    """
    weight = doc.weight_lbs  # type: ignore[assignment]  # non-None guaranteed by caller

    if weight <= MAX_WEIGHT_LBS:
        return []

    excess = weight - MAX_WEIGHT_LBS
    return [
        ValidationIssue(
            code=IssueCode.OVERWEIGHT_LOAD,
            severity=Severity.WARNING,
            message=(
                f"Weight {weight:,} lbs exceeds the "
                f"{MAX_WEIGHT_LBS:,} lb limit by {excess:,} lbs."
            ),
            fields=["weight_lbs"],
        )
    ]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_blank(value: object) -> bool:
    """Return *True* if *value* is ``None`` or a whitespace-only string."""
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _rates_are_present(doc: FreightDocument) -> bool:
    """Return *True* when all three rate fields are non-None and non-blank."""
    return (
        not _is_blank(doc.total_linehaul_rate)
        and not _is_blank(doc.fuel_surcharge)
        and not _is_blank(doc.total_pay)
    )
