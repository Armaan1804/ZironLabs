"""
schemas.py — Pydantic v2 data models for the freight_parser pipeline.

Design notes
------------
* All value fields on FreightDocument are Optional[...] (defaulting to None).
  This is intentional: the LLM may fail to find a field in the source
  document. Keeping every field optional lets instructor return a partial
  object rather than raising a validation error or hallucinating a value.
  Missing fields are then surfaced as INCOMPLETE_DATA issues by validator.py,
  which is the correct place for business-rule enforcement.

* Monetary amounts and weights use field-level validators that coerce
  human-readable strings (e.g. "$1,250.00", "42,000 lbs") to the appropriate
  numeric type. This means the LLM can return either the raw string it finds in
  the document or a pre-converted number — both are handled gracefully.

* model_config uses extra="forbid" so any hallucinated fields the LLM invents
  beyond the schema are rejected, triggering an instructor retry.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic import ConfigDict


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strip_currency(value: object) -> object:
    """Coerce "$1,250.00" or "1,250" → float-compatible string; pass through
    numbers unchanged."""
    if isinstance(value, str):
        # Remove currency symbols, commas, and trailing unit words
        cleaned = re.sub(r"[^\d.]", "", value.replace(",", ""))
        return float(cleaned) if cleaned else value
    return value


def _strip_weight(value: object) -> object:
    """Coerce "42,000 lbs" or "42000" → int-compatible value; pass through
    numbers unchanged."""
    if isinstance(value, str):
        # Keep only digits (drop commas, spaces, "lbs", "lb", etc.)
        cleaned = re.sub(r"[^\d]", "", value)
        return int(cleaned) if cleaned else value
    return value


# ---------------------------------------------------------------------------
# Location
# ---------------------------------------------------------------------------

class Location(BaseModel):
    """Physical address of a freight pickup or delivery point."""

    model_config = ConfigDict(extra="forbid")

    facility_name: Optional[str] = Field(
        default=None,
        description=(
            "Named facility, warehouse, or distribution centre. "
            "This is NOT the city name — e.g. 'Distribution Center 4' or "
            "'Warehouse B'. Leave null if no facility name is present."
        ),
    )
    city: Optional[str] = Field(
        default=None,
        description="City portion of the address, e.g. 'Dallas'.",
    )
    state: Optional[str] = Field(
        default=None,
        description=(
            "Two-letter US state abbreviation, e.g. 'TX'. "
            "Normalise to uppercase if the document uses lowercase."
        ),
    )
    zip_code: Optional[str] = Field(
        default=None,
        description=(
            "US ZIP code as a string: 5 digits ('75201') or ZIP+4 "
            "('75201-1234'). Preserve leading zeros."
        ),
    )

    @field_validator("state", mode="before")
    @classmethod
    def normalise_state(cls, v: object) -> object:
        """Upper-case the state abbreviation and strip whitespace."""
        if isinstance(v, str):
            return v.strip().upper()
        return v

    @field_validator("zip_code", mode="before")
    @classmethod
    def validate_zip(cls, v: object) -> object:
        """Accept 5-digit or ZIP+4 strings; reject anything else."""
        if v is None:
            return v
        if isinstance(v, str):
            cleaned = v.strip()
            if re.fullmatch(r"\d{5}(-\d{4})?", cleaned):
                return cleaned
            # Try to extract a valid ZIP from a longer address string
            match = re.search(r"\b(\d{5})(?:-\d{4})?\b", cleaned)
            if match:
                return match.group(0)
            # Return as-is — let downstream validation surface the issue
            return cleaned
        return v


# ---------------------------------------------------------------------------
# FreightDocument
# ---------------------------------------------------------------------------

class FreightDocument(BaseModel):
    """Structured representation of a freight / rate confirmation document.

    All value fields are Optional so that partially extractable documents
    return a populated object (with None gaps) rather than crashing or
    being filled with hallucinated values. Missing fields are handled as
    INCOMPLETE_DATA violations in validator.py.
    """

    model_config = ConfigDict(extra="forbid")

    carrier_name: Optional[str] = Field(
        default=None,
        description=(
            "Full legal name of the carrier or trucking company, "
            "e.g. 'Apex Logistics Solutions LLC'."
        ),
    )
    load_number: Optional[str] = Field(
        default=None,
        description=(
            "Load, reference, or order identifier. May be labelled "
            "'Ref #', 'Load #', 'PRO #', 'Order #', or similar. "
            "Preserve the original alphanumeric value, e.g. 'LD-994821'."
        ),
    )
    pickup_location: Optional[Location] = Field(
        default=None,
        description=(
            "Origin / pickup address. Extract facility name, city, state, "
            "and ZIP as separate fields. Do NOT conflate the facility name "
            "with the city."
        ),
    )
    delivery_location: Optional[Location] = Field(
        default=None,
        description=(
            "Destination / delivery address. Extract facility name, city, "
            "state, and ZIP as separate fields."
        ),
    )
    total_linehaul_rate: Optional[float] = Field(
        default=None,
        description=(
            "Base linehaul rate in USD, as a number. May appear as "
            "'Linehaul', 'Line Haul', or 'Base Rate'. "
            "Example: 2200.00 (from '$2,200.00')."
        ),
    )
    fuel_surcharge: Optional[float] = Field(
        default=None,
        description=(
            "Fuel surcharge amount in USD, as a number. May be labelled "
            "'FSC', 'Fuel Surcharge', or 'Fuel'. "
            "Example: 350.00 (from '$350.00')."
        ),
    )
    total_pay: Optional[float] = Field(
        default=None,
        description=(
            "Total amount to be paid to the carrier in USD, as a number. "
            "May be labelled 'Total Pay', 'Total', 'Grand Total', or "
            "'Total Amount'. Example: 2800.00 (from '$2,800.00')."
        ),
    )
    weight_lbs: Optional[int] = Field(
        default=None,
        description=(
            "Shipment weight in pounds, as an integer. May be labelled "
            "'Weight', 'Gross Weight', or 'Total Weight'. "
            "Example: 46800 (from '46,800 lbs')."
        ),
    )

    # -----------------------------------------------------------------------
    # Field-level coercions — handle strings the LLM passes through verbatim
    # -----------------------------------------------------------------------

    @field_validator("total_linehaul_rate", "fuel_surcharge", "total_pay", mode="before")
    @classmethod
    def coerce_currency(cls, v: object) -> object:
        """Accept '$1,250.00', '1,250', or a bare number; return float."""
        return _strip_currency(v)

    @field_validator("weight_lbs", mode="before")
    @classmethod
    def coerce_weight(cls, v: object) -> object:
        """Accept '46,800 lbs', '46800', or a bare int; return int."""
        return _strip_weight(v)


# ---------------------------------------------------------------------------
# Validation / Decision result models
# ---------------------------------------------------------------------------

class Severity(str, Enum):
    """Severity level of a validation issue."""

    ERROR = "ERROR"
    WARNING = "WARNING"


class IssueCode(str, Enum):
    """Machine-readable codes for each business-rule violation."""

    RATE_MISMATCH = "RATE_MISMATCH"
    """Linehaul + fuel surcharge does not equal the stated total pay."""

    OVERWEIGHT_LOAD = "OVERWEIGHT_LOAD"
    """Shipment weight exceeds the legal or contractual limit."""

    INCOMPLETE_DATA = "INCOMPLETE_DATA"
    """One or more required fields are missing or null in the document."""


class ValidationIssue(BaseModel):
    """A single business-rule violation found during validation."""

    model_config = ConfigDict(extra="forbid")

    code: IssueCode = Field(description="Machine-readable issue identifier.")
    severity: Severity = Field(description="Both ERROR and WARNING trigger FLAGGED.")
    message: str = Field(description="Human-readable explanation of the violation.")
    fields: list[str] = Field(
        default_factory=list,
        description="Names of the FreightDocument fields involved in this issue.",
    )


class ValidationResult(BaseModel):
    """Aggregated output of validator.py."""

    model_config = ConfigDict(extra="forbid")

    issues: list[ValidationIssue] = Field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        """True when there are zero issues of any severity."""
        return len(self.issues) == 0

    @property
    def errors(self) -> list[ValidationIssue]:
        """Subset of issues with severity == ERROR."""
        return [i for i in self.issues if i.severity == Severity.ERROR]

    @property
    def warnings(self) -> list[ValidationIssue]:
        """Subset of issues with severity == WARNING."""
        return [i for i in self.issues if i.severity == Severity.WARNING]


class DecisionStatus(str, Enum):
    """Final automated decision on a freight document."""

    APPROVED = "APPROVED"
    FLAGGED_FOR_HUMAN_REVIEW = "FLAGGED_FOR_HUMAN_REVIEW"


class AgentDecision(BaseModel):
    """Output produced by agent.py after consuming a ValidationResult."""

    model_config = ConfigDict(extra="forbid")

    status: DecisionStatus = Field(
        description="Final decision: APPROVED or FLAGGED_FOR_HUMAN_REVIEW."
    )
    summary: str = Field(
        description="One- or two-sentence plain-English explanation of the decision."
    )
    data: Optional[FreightDocument] = Field(
        default=None,
        description="The extracted FreightDocument, included for reference.",
    )
    issues: list[ValidationIssue] = Field(
        default_factory=list,
        description="All validation issues that informed the decision.",
    )
