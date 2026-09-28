"""
test_agent.py — Unit tests for freight_parser.agent.process_document().

All LLM calls are monkeypatched.  No real API calls are made.

Test groups
-----------
- APPROVED path    : clean doc → status APPROVED, data set, issues empty
- FLAGGED path     : sample doc (2 violations) → status FLAGGED, issues present,
                     summary contains issue codes and counts
- ExtractionError  : LLM failure → status FLAGGED, data=None, no exception raised
"""

import pytest

from freight_parser.agent import process_document
from freight_parser.errors import ExtractionError
from freight_parser.schemas import DecisionStatus, IssueCode


# ---------------------------------------------------------------------------
# APPROVED path
# ---------------------------------------------------------------------------


class TestApprovedPath:
    def test_status_is_approved(self, monkeypatch, clean_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: clean_doc,
        )
        decision = process_document("any text")
        assert decision.status == DecisionStatus.APPROVED

    def test_data_is_the_extracted_doc(self, monkeypatch, clean_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: clean_doc,
        )
        decision = process_document("any text")
        assert decision.data == clean_doc

    def test_issues_list_is_empty(self, monkeypatch, clean_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: clean_doc,
        )
        decision = process_document("any text")
        assert decision.issues == []

    def test_summary_is_non_empty(self, monkeypatch, clean_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: clean_doc,
        )
        decision = process_document("any text")
        assert len(decision.summary) > 0

    def test_approved_summary_positive_language(self, monkeypatch, clean_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: clean_doc,
        )
        decision = process_document("any text")
        summary_lower = decision.summary.lower()
        assert "passed" in summary_lower or "approved" in summary_lower or "valid" in summary_lower


# ---------------------------------------------------------------------------
# FLAGGED path — sample document (RATE_MISMATCH + OVERWEIGHT_LOAD)
# ---------------------------------------------------------------------------


class TestFlaggedPath:
    def test_status_is_flagged(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert decision.status == DecisionStatus.FLAGGED_FOR_HUMAN_REVIEW

    def test_data_is_the_extracted_doc(self, monkeypatch, sample_doc):
        """Reviewer must be able to see the parsed data even when flagged."""
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert decision.data == sample_doc

    def test_issues_list_has_two_entries(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert len(decision.issues) == 2

    def test_issues_contain_rate_mismatch(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        codes = [i.code for i in decision.issues]
        assert IssueCode.RATE_MISMATCH in codes

    def test_issues_contain_overweight_load(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        codes = [i.code for i in decision.issues]
        assert IssueCode.OVERWEIGHT_LOAD in codes

    def test_summary_mentions_error_count(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert "1 error" in decision.summary.lower()

    def test_summary_mentions_warning_count(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert "1 warning" in decision.summary.lower()

    def test_summary_contains_rate_mismatch_code(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert "RATE_MISMATCH" in decision.summary

    def test_summary_contains_overweight_code(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert "OVERWEIGHT_LOAD" in decision.summary

    def test_summary_mentions_flagged(self, monkeypatch, sample_doc):
        monkeypatch.setattr(
            "freight_parser.agent.extract_document",
            lambda text: sample_doc,
        )
        decision = process_document("any text")
        assert "flagged" in decision.summary.lower()


# ---------------------------------------------------------------------------
# ExtractionError path
# ---------------------------------------------------------------------------


class TestExtractionErrorPath:
    def _patch_extraction_error(self, monkeypatch, message: str = "API quota exceeded"):
        def _raise(_text):
            raise ExtractionError(message)
        monkeypatch.setattr("freight_parser.agent.extract_document", _raise)

    def test_returns_flagged_not_exception(self, monkeypatch):
        """ExtractionError must be caught; process_document must not raise."""
        self._patch_extraction_error(monkeypatch)
        decision = process_document("any text")   # must not raise
        assert decision.status == DecisionStatus.FLAGGED_FOR_HUMAN_REVIEW

    def test_data_is_none_when_extraction_fails(self, monkeypatch):
        """No FreightDocument was produced — data must be None."""
        self._patch_extraction_error(monkeypatch)
        decision = process_document("any text")
        assert decision.data is None

    def test_issues_list_is_empty_when_extraction_fails(self, monkeypatch):
        """No validation was possible — issues list should be empty."""
        self._patch_extraction_error(monkeypatch)
        decision = process_document("any text")
        assert decision.issues == []

    def test_summary_contains_original_error_message(self, monkeypatch):
        self._patch_extraction_error(monkeypatch, "API quota exceeded")
        decision = process_document("any text")
        assert "API quota exceeded" in decision.summary

    def test_summary_mentions_extraction_or_failed(self, monkeypatch):
        self._patch_extraction_error(monkeypatch, "network timeout")
        decision = process_document("any text")
        summary_lower = decision.summary.lower()
        assert "extraction" in summary_lower or "failed" in summary_lower or "error" in summary_lower

    def test_different_error_messages_propagated(self, monkeypatch):
        self._patch_extraction_error(monkeypatch, "Connection refused")
        decision = process_document("any text")
        assert "Connection refused" in decision.summary
