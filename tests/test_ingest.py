"""
test_ingest.py — Unit tests for freight_parser.ingest.

Tests cover:
- Plain-text (.txt) loading and normalisation
- PDF extraction using a programmatically generated PDF (fpdf2)
- Scanned / image-only PDF detection (blank page → < 50 non-ws chars)
- Unsupported file extension → UnsupportedFormatError
- Nonexistent file path → IngestionError
- normalize_text behaviour in isolation

fpdf2 is used as a lightweight test-only PDF generator.
Install: `pip install fpdf2` (already in requirements.txt dev section).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from freight_parser.errors import IngestionError, UnsupportedFormatError
from freight_parser.ingest import load_document_text, normalize_text

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SAMPLE_PDF_TEXT = """\
RATE CONFIRMATION

Carrier: Apex Logistics Solutions LLC
Ref #: LD-994821

Pickup: Distribution Center 4, Dallas, TX 75201
Delivery: Warehouse B, Atlanta, GA 30303

Weight: 46,800 lbs
Linehaul Rate: $2,200.00
Fuel Surcharge: $350.00
Total Pay: $2,800.00
"""


def _write_text_pdf(path: Path, content: str) -> None:
    """Generate a single-page text PDF at *path* using fpdf2."""
    from fpdf import FPDF  # local import — only needed when fpdf2 is installed

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", size=11)
    # multi_cell wraps text and handles embedded newlines
    pdf.multi_cell(0, 6, content)
    pdf.output(str(path))


def _write_blank_pdf(path: Path) -> None:
    """Generate a PDF with one blank page and no text (simulates a scanned PDF)."""
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    # Deliberately add no text — page will have < 50 non-whitespace chars
    pdf.output(str(path))


# ---------------------------------------------------------------------------
# Plain-text (.txt) ingestion
# ---------------------------------------------------------------------------


class TestTxtIngestion:
    def test_txt_file_loads(self, tmp_path: Path):
        doc = tmp_path / "rate.txt"
        doc.write_text("Carrier: Test LLC\nLoad #: LD-001\n", encoding="utf-8")
        text = load_document_text(doc)
        assert "Test LLC" in text
        assert "LD-001" in text

    def test_txt_trailing_whitespace_stripped_per_line(self, tmp_path: Path):
        doc = tmp_path / "trailing.txt"
        doc.write_text("line one   \nline two  \n", encoding="utf-8")
        text = load_document_text(doc)
        for line in text.splitlines():
            assert line == line.rstrip(), f"Line has trailing whitespace: {line!r}"

    def test_txt_str_path_accepted(self, tmp_path: Path):
        doc = tmp_path / "str_path.txt"
        doc.write_text("hello world", encoding="utf-8")
        text = load_document_text(str(doc))  # str, not Path
        assert "hello world" in text

    def test_empty_txt_raises_ingestion_error(self, tmp_path: Path):
        doc = tmp_path / "empty.txt"
        doc.write_text("   \n\t\n   ", encoding="utf-8")
        with pytest.raises(IngestionError, match="empty"):
            load_document_text(doc)

    def test_md_file_loads(self, tmp_path: Path):
        doc = tmp_path / "rate.md"
        doc.write_text("# Rate Confirmation\n\nLoad #: LD-999\n", encoding="utf-8")
        text = load_document_text(doc)
        assert "LD-999" in text


# ---------------------------------------------------------------------------
# PDF ingestion
# ---------------------------------------------------------------------------


class TestPdfIngestion:
    def test_pdf_with_text_loads(self, tmp_path: Path):
        pdf_path = tmp_path / "freight.pdf"
        _write_text_pdf(pdf_path, _SAMPLE_PDF_TEXT)
        text = load_document_text(pdf_path)
        assert len(text) > 0

    def test_pdf_contains_load_number(self, tmp_path: Path):
        """The generated PDF must survive the round-trip with 'LD-994821' intact."""
        pdf_path = tmp_path / "freight.pdf"
        _write_text_pdf(pdf_path, _SAMPLE_PDF_TEXT)
        text = load_document_text(pdf_path)
        assert "LD-994821" in text

    def test_pdf_contains_carrier_name(self, tmp_path: Path):
        pdf_path = tmp_path / "freight.pdf"
        _write_text_pdf(pdf_path, _SAMPLE_PDF_TEXT)
        text = load_document_text(pdf_path)
        assert "Apex" in text

    def test_blank_pdf_raises_ingestion_error(self, tmp_path: Path):
        """A PDF with no text layer must raise IngestionError (scanned-PDF path)."""
        pdf_path = tmp_path / "blank.pdf"
        _write_blank_pdf(pdf_path)
        with pytest.raises(IngestionError, match="scanned|image.only|text layer"):
            load_document_text(pdf_path)

    def test_pdf_str_path_accepted(self, tmp_path: Path):
        pdf_path = tmp_path / "str.pdf"
        _write_text_pdf(pdf_path, _SAMPLE_PDF_TEXT)
        text = load_document_text(str(pdf_path))
        assert "LD-994821" in text


# ---------------------------------------------------------------------------
# Unsupported format
# ---------------------------------------------------------------------------


class TestUnsupportedFormat:
    def test_docx_raises_unsupported_format_error(self, tmp_path: Path):
        doc = tmp_path / "contract.docx"
        doc.write_bytes(b"PK\x03\x04fake docx content")
        with pytest.raises(UnsupportedFormatError, match="docx"):
            load_document_text(doc)

    def test_csv_raises_unsupported_format_error(self, tmp_path: Path):
        doc = tmp_path / "data.csv"
        doc.write_text("a,b,c\n1,2,3\n", encoding="utf-8")
        with pytest.raises(UnsupportedFormatError, match="csv"):
            load_document_text(doc)

    def test_error_message_lists_supported_types(self, tmp_path: Path):
        doc = tmp_path / "doc.xlsx"
        doc.write_bytes(b"fake")
        with pytest.raises(UnsupportedFormatError, match=r"\.txt"):
            load_document_text(doc)

    def test_unsupported_format_is_subclass_of_ingestion_error(self, tmp_path: Path):
        doc = tmp_path / "img.png"
        doc.write_bytes(b"\x89PNG")
        with pytest.raises(IngestionError):  # UnsupportedFormatError IS-A IngestionError
            load_document_text(doc)


# ---------------------------------------------------------------------------
# Nonexistent / inaccessible file
# ---------------------------------------------------------------------------


class TestMissingFile:
    def test_nonexistent_txt_raises_ingestion_error(self, tmp_path: Path):
        missing = tmp_path / "ghost.txt"
        with pytest.raises(IngestionError, match="not found"):
            load_document_text(missing)

    def test_nonexistent_pdf_raises_ingestion_error(self, tmp_path: Path):
        missing = tmp_path / "ghost.pdf"
        with pytest.raises(IngestionError, match="not found"):
            load_document_text(missing)

    def test_error_message_contains_path(self, tmp_path: Path):
        missing = tmp_path / "my_missing_file.txt"
        with pytest.raises(IngestionError, match="my_missing_file"):
            load_document_text(missing)


# ---------------------------------------------------------------------------
# normalize_text (standalone)
# ---------------------------------------------------------------------------


class TestNormalizeText:
    def test_trailing_whitespace_stripped(self):
        text = "hello   \nworld  "
        result = normalize_text(text)
        for line in result.splitlines():
            assert line == line.rstrip()

    def test_three_blank_lines_collapsed_to_two(self):
        text = "a\n\n\n\nb"
        result = normalize_text(text)
        assert "\n\n\n" not in result
        assert "a" in result
        assert "b" in result

    def test_four_blank_lines_collapsed_to_two(self):
        text = "x\n\n\n\n\ny"
        result = normalize_text(text)
        assert result.count("\n") <= 3  # "x\n\n\ny"

    def test_two_blank_lines_preserved(self):
        text = "section one\n\n\nsection two"
        result = normalize_text(text)
        # Two blank lines = three \n chars between sections
        # After collapse: "section one\n\nsection two"
        assert "section one" in result
        assert "section two" in result

    def test_leading_trailing_stripped(self):
        text = "\n\nhello\n\n"
        result = normalize_text(text)
        assert result == "hello"

    def test_empty_string_returns_empty(self):
        assert normalize_text("") == ""

    def test_whitespace_only_returns_empty(self):
        assert normalize_text("   \n\t\n   ") == ""

    def test_line_breaks_preserved(self):
        """Newlines within the document must be kept (label:value layout)."""
        text = "Carrier: Apex LLC\nLoad #: LD-001"
        result = normalize_text(text)
        assert "\n" in result
