"""Shared utilities for the backend."""
from datetime import datetime
from typing import Optional


def utc_isoformat(dt: Optional[datetime]) -> Optional[str]:
    """
    Serialize a datetime to ISO 8601 with trailing 'Z'.
    Handles both naive datetimes (from SQLite) and timezone-aware UTC datetimes.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.isoformat() + "Z"
    return dt.isoformat().replace("+00:00", "Z")
