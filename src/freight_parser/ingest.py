"""
ingest.py — Document ingestion layer for the freight_parser pipeline.

Responsibilities
----------------
* Read a freight document from disk (.txt, .md, .pdf) and return its content
  as a single plain-text string.
* Normalize the text so downstream modules receive consistent whitespace.

Rules
-----
* This module only knows about files and text.  It MUST NOT import anything
  from extractor.py, validator.py, agent.py, or cli.py.
* All error conditions surface as typed exceptions (IngestionError /
  UnsupportedFormatError) — never as raw tracebacks.

Future work
-----------
* OCR support for scanned PDFs (e.g. via pytesseract + pdf2image).
  Currently raises IngestionError when fewer than 50 non-whitespace characters
  are found in the extracted text.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import pdfplumber

from freight_parser.errors import IngestionError, UnsupportedFormatError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: File extensions this module can handle.
SUPPORTED_EXTENSIONS: tuple[str, ...] = (".txt", ".md", ".pdf")

#: Minimum non-whitespace character count before we consider a PDF text-less.
_MIN_PDF_CHARS = 50

#: Collapse runs of 3+ consecutive blank lines down to exactly 2.
_EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load_document_text(path: str | Path) -> str:
    """Load a freight document from *path* and return its plain-text content.

    Dispatches to the appropriate reader based on file extension, then
    normalizes the result via :func:`normalize_text`.

    Parameters
    ----------
    path:
        Filesystem path to a ``.txt``, ``.md``, or ``.pdf`` file.

    Returns
    -------
    str
        Normalized plain-text content of the document.

    Raises
    ------
    IngestionError
        If the file does not exist, is corrupt, is password-protected, or is
        a scanned PDF with no extractable text layer.
    UnsupportedFormatError
        If the file extension is not in ``SUPPORTED_EXTENSIONS``.
    """
    resolved = _resolve_path(path)
    ext = resolved.suffix.lower()

    log.debug("Ingesting file: %s (extension: %s)", resolved, ext)

    if ext in (".txt", ".md"):
        raw = _read_text_file(resolved)
    elif ext == ".pdf":
        raw = _read_pdf(resolved)
    else:
        supported = ", ".join(SUPPORTED_EXTENSIONS)
        raise UnsupportedFormatError(
            f"Unsupported file format '{ext}'. "
            f"Supported formats: {supported}. "
            "Pass a .txt, .md, or .pdf file, or pipe text via stdin."
        )

    normalized = normalize_text(raw)
    log.debug(
        "Ingestion complete: %d characters after normalization.", len(normalized)
    )
    return normalized


def normalize_text(text: str) -> str:
    """Normalize whitespace in *text* without altering semantic content.

    Transformations applied (in order):

    1. Strip trailing whitespace from every line (leading whitespace is
       preserved — indentation can be meaningful in label:value layouts).
    2. Collapse runs of three or more consecutive blank lines into exactly
       two blank lines.
    3. Strip leading/trailing whitespace from the overall string.

    Line breaks are **intentionally preserved** because the label:value layout
    of freight documents (e.g. ``Carrier: Apex Logistics LLC``) depends on
    newlines for correct LLM parsing.

    Parameters
    ----------
    text:
        Raw text string, e.g. from a file read or stdin.

    Returns
    -------
    str
        Whitespace-normalized text.
    """
    # Step 1 — strip trailing whitespace per line
    lines = [line.rstrip() for line in text.splitlines()]
    joined = "\n".join(lines)

    # Step 2 — collapse 3+ blank lines → 2 blank lines
    collapsed = _EXCESS_BLANK_LINES.sub("\n\n", joined)

    # Step 3 — trim the whole string
    return collapsed.strip()


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _resolve_path(path: str | Path) -> Path:
    """Convert *path* to an absolute :class:`~pathlib.Path` and assert it
    exists.

    Raises
    ------
    IngestionError
        If the resolved path does not point to an existing file.
    """
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise IngestionError(
            f"File not found: '{resolved}'. "
            "Check the path and try again."
        )
    if not resolved.is_file():
        raise IngestionError(
            f"Path '{resolved}' exists but is not a file."
        )
    return resolved


def _read_text_file(path: Path) -> str:
    """Read a plain-text or Markdown file as UTF-8.

    Uses ``errors='replace'`` so that documents with stray non-UTF-8 bytes
    (e.g. Windows-1252 curly quotes) do not raise a ``UnicodeDecodeError``;
    the replacement character (U+FFFD) is innocuous for our use-case.

    Parameters
    ----------
    path:
        Resolved path to the ``.txt`` or ``.md`` file.

    Returns
    -------
    str
        Raw file contents.

    Raises
    ------
    IngestionError
        On any OS-level read error.
    """
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise IngestionError(
            f"Could not read file '{path}': {exc.strerror}."
        ) from exc

    if not content.strip():
        raise IngestionError(
            f"File '{path}' is empty — no text content found."
        )

    log.debug("Read %d characters from text file '%s'.", len(content), path)
    return content


def _read_pdf(path: Path) -> str:
    """Extract text from a PDF file page by page using pdfplumber.

    Pages are joined with a blank line so that layout boundaries are preserved
    for the LLM.

    Parameters
    ----------
    path:
        Resolved path to the ``.pdf`` file.

    Returns
    -------
    str
        Concatenated text of all pages (pages separated by ``\\n\\n``).

    Raises
    ------
    IngestionError
        * If the PDF is password-protected.
        * If the PDF is corrupt or cannot be parsed.
        * If the extracted text has fewer than :data:`_MIN_PDF_CHARS`
          non-whitespace characters (scanned / image-only PDF).
    """
    try:
        with pdfplumber.open(path) as pdf:
            # pdfplumber raises pdfminer.pdfdocument.PDFPasswordIncorrect for
            # encrypted files that require a password.
            page_texts: list[str] = []
            for page_num, page in enumerate(pdf.pages, start=1):
                text = page.extract_text() or ""
                page_texts.append(text)
                log.debug(
                    "PDF page %d: extracted %d characters.", page_num, len(text)
                )

    except Exception as exc:  # noqa: BLE001
        # Covers PDFPasswordIncorrect, PDFSyntaxError, and any other
        # pdfplumber / pdfminer parse failure.
        exc_name = type(exc).__name__
        if "password" in exc_name.lower() or "password" in str(exc).lower():
            raise IngestionError(
                f"PDF '{path}' is password-protected. "
                "Remove the password and try again."
            ) from exc
        raise IngestionError(
            f"Failed to parse PDF '{path}': {exc}. "
            "The file may be corrupt or in an unsupported PDF variant."
        ) from exc

    full_text = "\n\n".join(page_texts)

    non_ws_count = len(full_text.replace(" ", "").replace("\n", "").replace("\t", ""))
    log.debug(
        "PDF '%s': %d non-whitespace characters across %d pages.",
        path,
        non_ws_count,
        len(page_texts),
    )

    if non_ws_count < _MIN_PDF_CHARS:
        raise IngestionError(
            f"PDF '{path}' appears to be scanned or image-only; "
            "no text layer found. "
            "OCR support is not implemented — see 'Future work' in ingest.py."
        )

    return full_text
