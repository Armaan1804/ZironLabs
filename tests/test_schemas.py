"""
test_schemas.py — Unit tests for Pydantic v2 schemas in freight_parser.schemas.

Covers:
- Currency string coercion  ("$1,250.00" → 1250.0)
- Weight string coercion    ("42,000 lbs" → 42000)
- State normalisation       ("tx" → "TX")
- ZIP validation / extraction
- Optional / null acceptance for all value fields
- extra="forbid" enforcement on FreightDocument and Location
"""

import pytest
from pydantic import ValidationError

from freight_parser.schemas import (
    AgentDecision,
    DecisionStatus,
    FreightDocument,
    IssueCode,
    Location,
    Severity,
    ValidationIssue,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Location — state normalisation
# ---------------------------------------------------------------------------


class TestLocationStateNormalisation:
    def test_lowercase_state_uppercased(self):
        loc = Location(city="Dallas", state="tx", zip_code="75201")
        assert loc.state == "TX"

    def test_mixed_case_state_uppercased(self):
        loc = Location(city="Atlanta", state="Ga", zip_code="30303")
        assert loc.state == "GA"

    def test_state_whitespace_stripped(self):
        loc = Location(city="Dallas", state="  TX  ", zip_code="75201")
        assert loc.state == "TX"

    def test_none_state_stays_none(self):
        loc = Location()
        assert loc.state is None


# ---------------------------------------------------------------------------
# Location — ZIP normalisation
# ---------------------------------------------------------------------------


class TestLocationZipNormalisation:
    def test_valid_5_digit_zip(self):
        loc = Location(zip_code="75201")
        assert loc.zip_code == "75201"

    def test_valid_zip_plus_4(self):
        loc = Location(zip_code="30303-1234")
        assert loc.zip_code == "30303-1234"

    def test_zip_extracted_from_padded_string(self):
        loc = Location(zip_code="  75201  ")
        assert loc.zip_code == "75201"

    def test_zip_extracted_from_longer_address(self):
        # The validator regex extracts the first 5-digit block
        loc = Location(zip_code="Dallas TX 75201")
        assert loc.zip_code == "75201"

    def test_none_zip_stays_none(self):
        loc = Location()
        assert loc.zip_code is None


# ---------------------------------------------------------------------------
# Location — all fields optional / null-safe
# ---------------------------------------------------------------------------


class TestLocationNulls:
    def test_empty_location_all_none(self):
        loc = Location()
        assert loc.facility_name is None
        assert loc.city is None
        assert loc.state is None
        assert loc.zip_code is None

    def test_partial_location_accepted(self):
        loc = Location(city="Dallas")
        assert loc.city == "Dallas"
        assert loc.state is None


# ---------------------------------------------------------------------------
# Location — extra fields rejected
# ---------------------------------------------------------------------------


class TestLocationExtraForbid:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError, match="extra"):
            Location(city="Dallas", state="TX", zip_code="75201", country="USA")


# ---------------------------------------------------------------------------
# FreightDocument — currency coercion
# ---------------------------------------------------------------------------


class TestCurrencyCoercion:
    def test_dollar_sign_and_commas_stripped(self):
        doc = FreightDocument(
            total_linehaul_rate="$2,200.00",
            fuel_surcharge="$350.00",
            total_pay="$2,800.00",
        )
        assert doc.total_linehaul_rate == 2200.0
        assert doc.fuel_surcharge == 350.0
        assert doc.total_pay == 2800.0

    def test_commas_only_stripped(self):
        doc = FreightDocument(total_linehaul_rate="1,250.50")
        assert doc.total_linehaul_rate == 1250.5

    def test_bare_float_passthrough(self):
        doc = FreightDocument(total_linehaul_rate=999.99)
        assert doc.total_linehaul_rate == 999.99

    def test_bare_int_coerced_to_float(self):
        doc = FreightDocument(fuel_surcharge=350)
        assert doc.fuel_surcharge == 350.0

    def test_string_integer_coerced(self):
        doc = FreightDocument(total_pay="2800")
        assert doc.total_pay == 2800.0


# ---------------------------------------------------------------------------
# FreightDocument — weight coercion
# ---------------------------------------------------------------------------


class TestWeightCoercion:
    def test_lbs_unit_and_commas_stripped(self):
        doc = FreightDocument(weight_lbs="46,800 lbs")
        assert doc.weight_lbs == 46800

    def test_lb_unit_stripped(self):
        doc = FreightDocument(weight_lbs="42,000 lb")
        assert doc.weight_lbs == 42000

    def test_commas_only_stripped(self):
        doc = FreightDocument(weight_lbs="40,000")
        assert doc.weight_lbs == 40000

    def test_bare_int_passthrough(self):
        doc = FreightDocument(weight_lbs=45000)
        assert doc.weight_lbs == 45000

    def test_string_integer_coerced(self):
        doc = FreightDocument(weight_lbs="38500")
        assert doc.weight_lbs == 38500


# ---------------------------------------------------------------------------
# FreightDocument — null / optional field acceptance
# ---------------------------------------------------------------------------


class TestFreightDocumentNulls:
    def test_fully_null_document_accepted(self):
        doc = FreightDocument()
        assert doc.carrier_name is None
        assert doc.load_number is None
        assert doc.pickup_location is None
        assert doc.delivery_location is None
        assert doc.total_linehaul_rate is None
        assert doc.fuel_surcharge is None
        assert doc.total_pay is None
        assert doc.weight_lbs is None

    def test_partial_document_accepted(self):
        doc = FreightDocument(carrier_name="Apex LLC", weight_lbs=40000)
        assert doc.carrier_name == "Apex LLC"
        assert doc.weight_lbs == 40000
        assert doc.load_number is None


# ---------------------------------------------------------------------------
# FreightDocument — extra fields rejected
# ---------------------------------------------------------------------------


class TestFreightDocumentExtraForbid:
    def test_extra_field_raises(self):
        with pytest.raises(ValidationError, match="extra"):
            FreightDocument(broker_name="Some Broker LLC")

    def test_another_extra_field_raises(self):
        with pytest.raises(ValidationError, match="extra"):
            FreightDocument(carrier_name="Test", pickup_date="2024-01-01")


# ---------------------------------------------------------------------------
# Result models — basic construction
# ---------------------------------------------------------------------------


class TestValidationResultProperties:
    def test_is_clean_true_when_no_issues(self):
        result = ValidationResult(issues=[])
        assert result.is_clean is True

    def test_is_clean_false_when_issues_exist(self):
        issue = ValidationIssue(
            code=IssueCode.RATE_MISMATCH,
            severity=Severity.ERROR,
            message="mismatch",
        )
        result = ValidationResult(issues=[issue])
        assert result.is_clean is False

    def test_errors_filters_by_severity(self):
        err = ValidationIssue(code=IssueCode.RATE_MISMATCH, severity=Severity.ERROR, message="e")
        warn = ValidationIssue(code=IssueCode.OVERWEIGHT_LOAD, severity=Severity.WARNING, message="w")
        result = ValidationResult(issues=[err, warn])
        assert result.errors == [err]
        assert result.warnings == [warn]


class TestDecisionStatusValues:
    """Ensure string values match the spec exactly (used in JSON output)."""

    def test_approved_value(self):
        assert DecisionStatus.APPROVED.value == "APPROVED"

    def test_flagged_value(self):
        assert DecisionStatus.FLAGGED_FOR_HUMAN_REVIEW.value == "FLAGGED_FOR_HUMAN_REVIEW"
