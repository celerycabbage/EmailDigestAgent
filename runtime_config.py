"""Reload user-editable runtime settings without overriding infrastructure env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values


ROOT = Path(__file__).resolve().parent
RUNTIME_KEYS = {
    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL_ID",
    "EMBEDDING_API_KEY", "EMBEDDING_BASE_URL", "EMBEDDING_MODEL_ID", "EMBEDDING_FALLBACK_TO_LOCAL",
    "LLM_INPUT_PRICE_PER_MILLION", "LLM_OUTPUT_PRICE_PER_MILLION",
    "IMAP_SERVER", "IMAP_PORT", "IMAP_USERNAME", "IMAP_PASSWORD",
    "SMTP_SERVER", "SMTP_PORT", "SMTP_SECURITY", "SMTP_USERNAME", "SMTP_PASSWORD",
    "REPORT_RECIPIENT", "APP_TIMEZONE",
}


def refresh_runtime_config(path: Path | None = None) -> None:
    """Refresh only app settings; keep Docker DATABASE_URL/Redis overrides intact."""
    for key, value in dotenv_values(path or ROOT / ".env").items():
        if key in RUNTIME_KEYS and value not in {None, ""}:
            os.environ[key] = str(value)

