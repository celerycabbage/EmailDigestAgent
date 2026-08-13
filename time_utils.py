"""Project-wide timezone helpers.

APP_TIMEZONE defaults to Asia/Shanghai so Docker's UTC system clock does not
change report timestamps or daily scheduling behavior.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DEFAULT_TIMEZONE = "Asia/Shanghai"


def app_timezone() -> ZoneInfo:
    name = os.getenv("APP_TIMEZONE", DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"无效的 APP_TIMEZONE：{name}") from error


def app_now() -> datetime:
    """Return a naive wall-clock datetime in the configured application zone."""
    return datetime.now(app_timezone()).replace(tzinfo=None)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)

