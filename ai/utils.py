"""Shared utilities for the backend."""
from datetime import datetime
from typing import Optional


def utc_isoformat(dt: Optional[datetime]) -> Optional[str]:
    """
    Serialize a datetime to ISO 8601 with a trailing 'Z' when the datetime is
    naive (UTC). This ensures JavaScript's Date() parses it as UTC so
    toLocaleTimeString() / toLocaleDateString() display correct local time.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat()
