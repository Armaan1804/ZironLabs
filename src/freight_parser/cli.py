"""
cli.py — Command-line interface for the freight_parser pipeline.

Usage
-----
File input (PDF or TXT)::

    python -m freight_parser.cli --file path/to/doc.pdf
    python -m freight_parser.cli --file path/to/doc.txt --output result.json

Stdin input::

    cat doc.txt | python -m freight_parser.cli

Exit codes
----------
0 — APPROVED
1 — FLAGGED_FOR_HUMAN_REVIEW
2 — Configuration, ingestion, or usage error (no stack trace printed)

Logging
-------
Set the ``LOG_LEVEL`` environment variable to control verbosity, e.g.
``LOG_LEVEL=DEBUG python -m freight_parser.cli --file doc.txt``.
Diagnostic output goes to stderr; the report goes to stdout.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from freight_parser.agent import process_document
from freight_parser.errors import (
    ConfigError,
    FreightParserError,
    IngestionError,
    UnsupportedFormatError,
)
from freight_parser.ingest import load_document_text, normalize_text
from freight_parser.schemas import DecisionStatus

# ---------------------------------------------------------------------------
# Logging setup — must happen before any other freight_parser import that logs
# ---------------------------------------------------------------------------

_LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING").upper()
logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, _LOG_LEVEL, logging.WARNING),
    format="%(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

_DIVIDER = "═" * 54
_THIN    = "─" * 54


def _fmt_optional(value: object, prefix: str = "") -> str:
    """Format an optional value; show '—' when absent."""
    if value is None:
        return "—"
    return f"{prefix}{value}"


def _fmt_money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"${value:,.2f}"


def _fmt_weight(value: int | None) -> str:
    if value is None:
        return "—"
    return f"{value:,} lbs"


def _print_report(decision, *, file=sys.stdout) -> None:
    """Print the human-readable validation report to *file* (default stdout)."""
    p = lambda *a, **kw: print(*a, **kw, file=file)  # noqa: E731

    doc = decision.data

    p(_DIVIDER)
    p("  FREIGHT DOCUMENT VALIDATION REPORT")
    p(_DIVIDER)

    if doc:
        # ── Carrier & reference ──────────────────────────────────────────────
        p(f"  Carrier      : {_fmt_optional(doc.carrier_name)}")
        p(f"  Load #       : {_fmt_optional(doc.load_number)}")
        p(_THIN)

        # ── Locations ────────────────────────────────────────────────────────
        def _fmt_location(loc) -> str:
            if loc is None:
                return "—"
            parts = []
            if loc.facility_name:
                parts.append(loc.facility_name)
            city_state_zip = ", ".join(filter(None, [loc.city, loc.state, loc.zip_code]))
            if city_state_zip:
                parts.append(city_state_zip)
            return ", ".join(parts) if parts else "—"

        p(f"  Origin       : {_fmt_location(doc.pickup_location)}")
        p(f"  Destination  : {_fmt_location(doc.delivery_location)}")
        p(_THIN)

        # ── Rates ────────────────────────────────────────────────────────────
        p(f"  Weight       : {_fmt_weight(doc.weight_lbs)}")
        p(f"  Linehaul     : {_fmt_money(doc.total_linehaul_rate)}")
        p(f"  Fuel Surcharge: {_fmt_money(doc.fuel_surcharge)}")
        p(f"  Total Pay    : {_fmt_money(doc.total_pay)}")
    else:
        p("  (No document data — extraction failed)")

    p(_THIN)

    # ── Issues ───────────────────────────────────────────────────────────────
    issues = decision.issues
    if issues:
        p(f"  ISSUES FOUND ({len(issues)}):")
        for issue in issues:
            fields_hint = f"  [fields: {', '.join(issue.fields)}]" if issue.fields else ""
            p(f"    [{issue.severity.value}] {issue.code.value}")
            p(f"      {issue.message}{fields_hint}")
    else:
        p("  No issues found.")

    p(_THIN)

    # ── Outcome ──────────────────────────────────────────────────────────────
    status = decision.status
    if status == DecisionStatus.APPROVED:
        outcome_line = "✅  APPROVED"
    else:
        outcome_line = "⛔  FLAGGED FOR HUMAN REVIEW"

    p(f"  OUTCOME: {outcome_line}")
    p(_DIVIDER)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freight-parser",
        description=(
            "Parse a freight/rate-confirmation document and validate it "
            "against business rules."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  freight-parser --file sample_data/rate_confirmation.pdf\n"
            "  freight-parser --file doc.txt --output result.json\n"
            "  cat doc.txt | freight-parser\n"
        ),
    )
    parser.add_argument(
        "--file", "-f",
        metavar="PATH",
        help=(
            "Path to a .txt, .md, or .pdf freight document. "
            "Omit to read from stdin."
        ),
    )
    parser.add_argument(
        "--output", "-o",
        metavar="PATH",
        help=(
            "Optional path to write the full AgentDecision JSON. "
            "The report is always printed to stdout."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the pipeline, print the report, return exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    # ── Step 1: ingest ───────────────────────────────────────────────────────
    try:
        if args.file:
            log.debug("Reading file: %s", args.file)
            raw_text = load_document_text(args.file)
        else:
            log.debug("Reading from stdin.")
            stdin_content = sys.stdin.read()
            if not stdin_content.strip():
                _error_exit("No input provided. Pass --file or pipe text via stdin.")
            raw_text = normalize_text(stdin_content)
    except UnsupportedFormatError as exc:
        _error_exit(str(exc))
    except IngestionError as exc:
        _error_exit(str(exc))
    except ConfigError as exc:
        _error_exit(str(exc))
    except FreightParserError as exc:
        _error_exit(str(exc))

    # ── Step 2: run pipeline (agent handles ConfigError / ExtractionError) ───
    try:
        decision = process_document(raw_text)
    except ConfigError as exc:
        # ConfigError surfaces here if get_config() fails inside build_client()
        _error_exit(str(exc))
    except Exception as exc:  # noqa: BLE001
        # Unexpected crash — still no raw traceback for the user
        log.exception("Unexpected error during pipeline execution.")
        _error_exit(f"Unexpected error: {exc}")

    # ── Step 3: print human-readable report ─────────────────────────────────
    _print_report(decision)

    # ── Step 4: pretty-print extracted JSON ─────────────────────────────────
    decision_dict = decision.model_dump(mode="json")
    pretty_json = json.dumps(decision_dict, indent=2, default=str)
    print("\nFull decision JSON:")
    print(pretty_json)

    # ── Step 5: optional JSON output file ───────────────────────────────────
    if args.output:
        out_path = Path(args.output)
        try:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(pretty_json, encoding="utf-8")
            print(f"\nDecision written to: {out_path.resolve()}")
            log.info("Decision JSON written to '%s'.", out_path.resolve())
        except OSError as exc:
            # Non-fatal: report was already printed to stdout
            print(
                f"\nWarning: could not write output file '{out_path}': {exc.strerror}.",
                file=sys.stderr,
            )

    # ── Step 6: exit code ────────────────────────────────────────────────────
    if decision.status == DecisionStatus.APPROVED:
        return 0
    return 1


def _error_exit(message: str) -> None:
    """Print *message* to stderr and exit with code 2.  Never returns."""
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(2)


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
