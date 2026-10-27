"""Date parsing with explicit formats only. The comments CSV writes `DD/MM/YYYY, HH:MM:SS`
in the ingest timezone (PERSOCIAL_TZ, default UTC); letting pandas guess would turn
01/02 into January 2nd."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from persocial.config import settings


def _tz() -> ZoneInfo:
    return ZoneInfo(settings().persocial_tz)


_FORMATS_LOCAL = (
    "%d/%m/%Y, %H:%M:%S",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y, %H:%M",
    "%d/%m/%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
)
_FILENAME_TS = re.compile(r"(\d{8})-(\d{6})")


def parse_local(value: str | None) -> datetime | None:
    """Comment/post timestamps. Explicit-offset ISO values keep their offset; everything
    naive is interpreted in PERSOCIAL_TZ (default UTC)."""
    if not value:
        return None
    v = value.strip()
    if not v:
        return None
    if v.endswith(" UTC"):
        try:
            return datetime.strptime(v[:-4], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            pass
    if re.search(r"(Z|[+-]\d{2}:?\d{2})$", v):
        try:
            return datetime.fromisoformat(v)  # requires-python >=3.11 parses trailing Z natively
        except ValueError:
            pass
    for fmt in _FORMATS_LOCAL:
        try:
            return datetime.strptime(v, fmt).replace(tzinfo=_tz())
        except ValueError:
            continue
    return None


def snapshot_time_from_filename(name: str) -> datetime | None:
    """`sample-20260617-114742.csv` -> 2026-06-17 11:47:42 in PERSOCIAL_TZ."""
    m = _FILENAME_TS.search(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=_tz())
    except ValueError:
        return None


def today_local() -> date:
    return datetime.now(_tz()).date()
