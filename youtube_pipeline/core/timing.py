from __future__ import annotations

from datetime import datetime, timezone
from time import monotonic
from typing import Optional


def parse_utc(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def elapsed_seconds(started_at: Optional[str], finished_at: Optional[str] = None) -> Optional[float]:
    start = parse_utc(started_at)
    end = parse_utc(finished_at) if finished_at else datetime.now(timezone.utc)
    if start is None or end is None:
        return None
    return max(0.0, (end - start).total_seconds())


def format_duration(seconds: Optional[float]) -> str:
    if seconds is None:
        return "00:00:00"
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class ElapsedTimer:
    """Monotonic timer for the current process execution."""

    def __init__(self) -> None:
        self._started = monotonic()

    @property
    def seconds(self) -> float:
        return max(0.0, monotonic() - self._started)

    @property
    def formatted(self) -> str:
        return format_duration(self.seconds)
