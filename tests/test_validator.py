"""
test_validator.py — Unit tests for freight_parser.validator.validate().

Every test in this module is a pure-function test: no mocks, no LLM calls,
no file I/O.  Each test constructs a FreightDocument directly and asserts on
the returned ValidationResult.

Test groups
-----------
- Clean document    → no issues
- RATE_MISMATCH     → correct trigger, message content, field list, Decimal precision
- OVERWEIGHT_LOAD   → boundary conditions (45 000 = pass, 45 001 = warn)
- INCOMPLETE_DATA   → per-field coverage, blank strings, null location blocks
- Multiple issues   → sample doc produces exactly two issues
- Skip logic        → rules are skipped when their inputs are missing
"""

import pytest

from freight_parser.schemas import FreightDocument, IssueCode, Location, Severity
from freight_parser.validator import MAX_WEIGHT_LBS, validate


# ---------------------------------------------------------------------------
# Helper — build a clean doc with selective overrides
# ---------------------------------------------------------------------------


def _make_doc(**overrides) -> FreightDocument:
    """Return a fully-valid FreightDocument with optional field overrides."""
    defaults: dict = dict(
        carrier_name="Swift Freight LLC",
        load_number="LD-001",
        pickup_location=Location(city="Dallas", state="TX", zip_code="75201"),
        delivery_location=Location(city="Atlanta", state="GA", zip_code="30303"),
        total_linehaul_rate=2200.00,
        fuel_surcharge=350.00,
        total_pay=2550.00,
        weight_lbs=40000,
    )
    defaults.update(overrides)
    return FreightDocument(**defaults)


# ---------------------------------------------------------------------------
# Clean document
# ---------------------------------------------------------------------------


class TestCleanDocument:
    def test_no_issues_on_valid_doc(self, clean_doc):
        result = validate(clean_doc)
        assert result.is_clean
        assert result.issues == []

    def test_errors_empty_on_valid_doc(self, clean_doc):
        assert validate(clean_doc).errors == []

    def test_warnings_empty_on_valid_doc(self, clean_doc):
        assert validate(clean_doc).warnings == []


# ---------------------------------------------------------------------------
# RATE_MISMATCH
# ---------------------------------------------------------------------------


class TestRateMismatch:
    def test_sample_doc_triggers_rate_mismatch(self, sample_doc):
        codes = [i.code for i in validate(sample_doc).issues]
        assert IssueCode.RATE_MISMATCH in codes

    def test_rate_mismatch_severity_is_error(self, sample_doc):
        issue = next(
            i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH
        )
        assert issue.severity == Severity.ERROR

    def test_rate_mismatch_message_has_linehaul(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH)
        assert "2200.00" in issue.message

    def test_rate_mismatch_message_has_fuel(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH)
        assert "350.00" in issue.message

    def test_rate_mismatch_message_has_computed_sum(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH)
        assert "2550.00" in issue.message

    def test_rate_mismatch_message_has_stated_total(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH)
        assert "2800.00" in issue.message

    def test_rate_mismatch_message_has_difference(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH)
        assert "250.00" in issue.message

    def test_rate_mismatch_fields_list(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.RATE_MISMATCH)
        assert set(issue.fields) == {"total_linehaul_rate", "fuel_surcharge", "total_pay"}

    def test_no_mismatch_when_rates_correct(self, clean_doc):
        codes = [i.code for i in validate(clean_doc).issues]
        assert IssueCode.RATE_MISMATCH not in codes

    def test_float_precision_no_false_flag(self):
        """1200.10 + 150.20 = 1350.30 in Decimal arithmetic — must not RATE_MISMATCH."""
        doc = _make_doc(
            total_linehaul_rate=1200.10,
            fuel_surcharge=150.20,
            total_pay=1350.30,
        )
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.RATE_MISMATCH not in codes

    def test_within_one_cent_tolerance_no_flag(self):
        """A $0.01 difference is within tolerance and must not flag."""
        doc = _make_doc(
            total_linehaul_rate=1000.00,
            fuel_surcharge=200.00,
            total_pay=1200.01,   # 1 cent over — within $0.01 tolerance
        )
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.RATE_MISMATCH not in codes

    def test_two_cent_difference_does_flag(self):
        """$0.02 difference exceeds the $0.01 tolerance and must flag."""
        doc = _make_doc(
            total_linehaul_rate=1000.00,
            fuel_surcharge=200.00,
            total_pay=1200.02,
        )
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.RATE_MISMATCH in codes

    def test_rate_mismatch_skipped_when_linehaul_missing(self):
        doc = _make_doc(total_linehaul_rate=None)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.RATE_MISMATCH not in codes

    def test_rate_mismatch_skipped_when_fuel_missing(self):
        doc = _make_doc(fuel_surcharge=None)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.RATE_MISMATCH not in codes

    def test_rate_mismatch_skipped_when_total_missing(self):
        doc = _make_doc(total_pay=None)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.RATE_MISMATCH not in codes


# ---------------------------------------------------------------------------
# OVERWEIGHT_LOAD
# ---------------------------------------------------------------------------


class TestOverweightLoad:
    def test_sample_doc_triggers_overweight(self, sample_doc):
        codes = [i.code for i in validate(sample_doc).issues]
        assert IssueCode.OVERWEIGHT_LOAD in codes

    def test_overweight_severity_is_warning(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.OVERWEIGHT_LOAD)
        assert issue.severity == Severity.WARNING

    def test_overweight_message_has_actual_weight(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.OVERWEIGHT_LOAD)
        assert "46,800" in issue.message

    def test_overweight_message_has_limit(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.OVERWEIGHT_LOAD)
        assert "45,000" in issue.message

    def test_overweight_message_has_excess(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.OVERWEIGHT_LOAD)
        assert "1,800" in issue.message

    def test_overweight_field_is_weight_lbs(self, sample_doc):
        issue = next(i for i in validate(sample_doc).issues if i.code == IssueCode.OVERWEIGHT_LOAD)
        assert issue.fields == ["weight_lbs"]

    def test_exactly_max_weight_does_not_flag(self):
        """45 000 lbs is the limit; it must NOT trigger OVERWEIGHT_LOAD."""
        doc = _make_doc(weight_lbs=MAX_WEIGHT_LBS)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.OVERWEIGHT_LOAD not in codes

    def test_one_pound_over_max_does_flag(self):
        """45 001 lbs is one over; it MUST trigger OVERWEIGHT_LOAD."""
        doc = _make_doc(weight_lbs=MAX_WEIGHT_LBS + 1)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.OVERWEIGHT_LOAD in codes

    def test_below_limit_no_warning(self):
        doc = _make_doc(weight_lbs=30000)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.OVERWEIGHT_LOAD not in codes

    def test_overweight_skipped_when_weight_missing(self):
        doc = _make_doc(weight_lbs=None)
        codes = [i.code for i in validate(doc).issues]
        assert IssueCode.OVERWEIGHT_LOAD not in codes


# ---------------------------------------------------------------------------
# INCOMPLETE_DATA
# ---------------------------------------------------------------------------


class TestIncompleteData:
    # ── Top-level scalar fields ──────────────────────────────────────────────

    def test_null_carrier_name_flagged(self):
        doc = _make_doc(carrier_name=None)
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "carrier_name" in fields

    def test_blank_carrier_name_flagged(self):
        """Whitespace-only string must also be treated as missing."""
        doc = _make_doc(carrier_name="   ")
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "carrier_name" in fields

    def test_null_load_number_flagged(self):
        doc = _make_doc(load_number=None)
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "load_number" in fields

    def test_null_weight_lbs_flagged(self):
        doc = _make_doc(weight_lbs=None)
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "weight_lbs" in fields

    # ── Location sub-fields ──────────────────────────────────────────────────

    def test_missing_pickup_city_flagged(self):
        doc = _make_doc(
            pickup_location=Location(city=None, state="TX", zip_code="75201")
        )
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "pickup_location.city" in fields

    def test_missing_pickup_state_flagged(self):
        doc = _make_doc(
            pickup_location=Location(city="Dallas", state=None, zip_code="75201")
        )
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "pickup_location.state" in fields

    def test_missing_pickup_zip_flagged(self):
        doc = _make_doc(
            pickup_location=Location(city="Dallas", state="TX", zip_code=None)
        )
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "pickup_location.zip_code" in fields

    def test_missing_delivery_city_flagged(self):
        doc = _make_doc(
            delivery_location=Location(city=None, state="GA", zip_code="30303")
        )
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "delivery_location.city" in fields

    def test_null_pickup_location_emits_three_subfield_issues(self):
        """When the entire pickup Location is None, each of its 3 required
        sub-fields must get its own INCOMPLETE_DATA issue."""
        doc = _make_doc(pickup_location=None)
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "pickup_location.city" in fields
        assert "pickup_location.state" in fields
        assert "pickup_location.zip_code" in fields

    def test_null_delivery_location_emits_three_subfield_issues(self):
        doc = _make_doc(delivery_location=None)
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        fields = [f for i in issues for f in i.fields]
        assert "delivery_location.city" in fields
        assert "delivery_location.state" in fields
        assert "delivery_location.zip_code" in fields

    # ── One issue per field ──────────────────────────────────────────────────

    def test_one_issue_per_missing_field(self):
        """A doc with two missing scalars must emit exactly two INCOMPLETE_DATA issues."""
        doc = _make_doc(carrier_name=None, load_number=None)
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        assert len(issues) == 2

    def test_incomplete_data_is_error_severity(self):
        doc = _make_doc(load_number=None)
        issue = next(i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA)
        assert issue.severity == Severity.ERROR

    # ── Fully null document ──────────────────────────────────────────────────

    def test_fully_null_doc_has_many_incomplete_data_issues(self):
        doc = FreightDocument()
        issues = [i for i in validate(doc).issues if i.code == IssueCode.INCOMPLETE_DATA]
        # 6 scalar fields + 3 pickup sub-fields + 3 delivery sub-fields = 12
        assert len(issues) == 12


# ---------------------------------------------------------------------------
# Multiple issues simultaneously
# ---------------------------------------------------------------------------


class TestMultipleIssues:
    def test_sample_doc_has_exactly_two_issues(self, sample_doc):
        result = validate(sample_doc)
        assert len(result.issues) == 2

    def test_sample_doc_one_error_one_warning(self, sample_doc):
        result = validate(sample_doc)
        assert len(result.errors) == 1
        assert len(result.warnings) == 1

    def test_sample_doc_not_clean(self, sample_doc):
        assert not validate(sample_doc).is_clean

    def test_sample_doc_error_is_rate_mismatch(self, sample_doc):
        result = validate(sample_doc)
        assert result.errors[0].code == IssueCode.RATE_MISMATCH

    def test_sample_doc_warning_is_overweight(self, sample_doc):
        result = validate(sample_doc)
        assert result.warnings[0].code == IssueCode.OVERWEIGHT_LOAD

    def test_doc_with_all_three_issue_types(self):
        """Missing field + rate mismatch + overweight must all appear."""
        doc = FreightDocument(
            carrier_name=None,          # INCOMPLETE_DATA
            load_number="LD-001",
            pickup_location=Location(city="Dallas", state="TX", zip_code="75201"),
            delivery_location=Location(city="Atlanta", state="GA", zip_code="30303"),
            total_linehaul_rate=2200.00,
            fuel_surcharge=350.00,
            total_pay=2800.00,          # RATE_MISMATCH
            weight_lbs=46800,           # OVERWEIGHT_LOAD
        )
        result = validate(doc)
        codes = {i.code for i in result.issues}
        assert IssueCode.INCOMPLETE_DATA in codes
        assert IssueCode.RATE_MISMATCH in codes
        assert IssueCode.OVERWEIGHT_LOAD in codes
