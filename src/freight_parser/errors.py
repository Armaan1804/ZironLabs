"""
errors.py — Custom exception hierarchy for freight_parser.

Every layer raises its own typed exception so the CLI can catch at the
appropriate boundary and show a clean message instead of a raw traceback.

Hierarchy:
    FreightParserError          ← base; catch-all in CLI
    ├── ConfigError             ← raised by config.py
    ├── IngestionError          ← raised by ingest.py
    │   └── UnsupportedFormatError
    └── ExtractionError         ← raised by extractor.py
"""


class FreightParserError(Exception):
    """Base exception for all freight_parser errors.

    All custom exceptions in this package inherit from this class so that
    callers can write a single ``except FreightParserError`` guard while still
    being able to distinguish sub-types when needed.
    """


class ConfigError(FreightParserError):
    """Raised when required configuration is absent or invalid.

    Examples
    --------
    - ``GEMINI_API_KEY`` environment variable is not set.
    - An unrecognised LLM provider name is specified.
    """


class IngestionError(FreightParserError):
    """Raised when a document cannot be read or converted to plain text.

    Examples
    --------
    - The file path does not exist.
    - The file is corrupt and cannot be opened.
    - A PDF contains only scanned images (no extractable text layer).
    - stdin is empty.
    """


class UnsupportedFormatError(IngestionError):
    """Raised when the supplied file extension is not supported.

    Inherits from :class:`IngestionError` so callers that only handle
    ``IngestionError`` still catch this automatically.

    Supported formats: ``.txt``, ``.pdf``, or stdin (no file argument).
    """


class ExtractionError(FreightParserError):
    """Raised when the LLM fails to return a valid :class:`FreightDocument`.

    Examples
    --------
    - The Gemini API returns a non-200 status.
    - ``instructor`` exhausts all retry attempts without a schema-conforming
      response.
    - The API key is valid but the quota is exceeded.
    """
