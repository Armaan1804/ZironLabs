"""
config.py — Application configuration loaded from environment / .env file.

Reads variables from the process environment (with python-dotenv pre-loading
the ``.env`` file if present) and exposes them as a frozen dataclass so the
rest of the package never has to call ``os.getenv`` directly.

Usage
-----
    from freight_parser.config import get_config

    cfg = get_config()
    print(cfg.api_key)      # Groq API key
    print(cfg.model_name)   # e.g. "llama-3.3-70b-versatile"
    print(cfg.max_retries)  # instructor retry budget
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

from freight_parser.errors import ConfigError

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported LLM providers — extend here if additional providers are added.
# ---------------------------------------------------------------------------
SUPPORTED_PROVIDERS: frozenset[str] = frozenset({"groq"})

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
_DEFAULT_MODEL = "llama-3.3-70b-versatile"
_DEFAULT_PROVIDER = "groq"
_DEFAULT_MAX_RETRIES = 3


@dataclass(frozen=True)
class AppConfig:
    """Immutable application configuration.

    Attributes
    ----------
    provider:
        LLM provider identifier (currently only ``"groq"`` is supported).
    api_key:
        Provider API key sourced from ``GROQ_API_KEY``.
    model_name:
        Model identifier forwarded to the LLM client, e.g.
        ``"llama-3.3-70b-versatile"``.
    max_retries:
        Number of times ``instructor`` will retry a malformed LLM response
        before raising :class:`~freight_parser.errors.ExtractionError`.
    """

    provider: str
    api_key: str
    model_name: str
    max_retries: int


def get_config() -> AppConfig:
    """Load and return the application configuration.

    Reads ``.env`` from the current working directory (if present), then
    validates the required variables.

    Returns
    -------
    AppConfig
        A frozen dataclass with all resolved configuration values.

    Raises
    ------
    ConfigError
        If ``GROQ_API_KEY`` is missing or empty, or if the requested
        provider is not supported.
    """
    # Load .env into os.environ if the file exists (safe no-op otherwise).
    load_dotenv(override=False)

    # ---- Provider ----------------------------------------------------------
    provider = os.getenv("LLM_PROVIDER", _DEFAULT_PROVIDER).strip().lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise ConfigError(
            f"Unsupported LLM provider: '{provider}'. "
            f"Supported providers: {', '.join(sorted(SUPPORTED_PROVIDERS))}. "
            "Set the LLM_PROVIDER environment variable to a supported value."
        )

    # ---- API Key -----------------------------------------------------------
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        raise ConfigError(
            "GROQ_API_KEY is not set. "
            "Copy .env.example to .env and add your Groq API key, "
            "or export GROQ_API_KEY=<your-key> in your shell."
        )

    # ---- Model name --------------------------------------------------------
    model_name = os.getenv("GROQ_MODEL", _DEFAULT_MODEL).strip()
    if not model_name:
        raise ConfigError(
            "GROQ_MODEL is set but empty. "
            f"Remove the variable to use the default ('{_DEFAULT_MODEL}') "
            "or provide a valid model name."
        )

    # ---- Retry budget ------------------------------------------------------
    raw_retries = os.getenv("EXTRACTOR_MAX_RETRIES", str(_DEFAULT_MAX_RETRIES))
    try:
        max_retries = int(raw_retries)
        if max_retries < 0:
            raise ValueError("must be non-negative")
    except ValueError:
        raise ConfigError(
            f"EXTRACTOR_MAX_RETRIES must be a non-negative integer; "
            f"got '{raw_retries}'."
        )

    cfg = AppConfig(
        provider=provider,
        api_key=api_key,
        model_name=model_name,
        max_retries=max_retries,
    )
    log.debug(
        "Config loaded: provider=%s model=%s max_retries=%d",
        cfg.provider,
        cfg.model_name,
        cfg.max_retries,
    )
    return cfg
