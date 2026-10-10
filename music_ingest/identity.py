"""Strict recording identifiers; release-track MBIDs must never be used here."""
import re
from uuid import UUID


def mbid(value) -> str | None:
    try:
        return str(UUID(str(value))) if value else None
    except (ValueError, TypeError, AttributeError):
        return None


def isrc(value) -> str | None:
    value = str(value or '').replace('-', '').upper()
    return value if re.fullmatch(r'[A-Z]{2}[A-Z0-9]{3}\d{7}', value) else None
