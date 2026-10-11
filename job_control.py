"""Small, independently testable helpers for rendering-job progress."""
from __future__ import annotations

import math
import re


def remaining_seconds(total_seconds: float | None, processed_seconds: float, speed: str) -> int | None:
    """Estimate remaining wall time only when FFmpeg supplies a valid speed.

    Does not claim an ETA during Twitch downloads or before FFmpeg has measured
    processing speed.
    """
    if total_seconds is None or not math.isfinite(total_seconds) or total_seconds <= 0:
        return None
    if not math.isfinite(processed_seconds) or processed_seconds < 0:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)x\s*", str(speed))
    if not match:
        return None
    rate = float(match.group(1))
    if rate <= 0 or not math.isfinite(rate):
        return None
    return math.ceil(max(0.0, total_seconds - processed_seconds) / rate)


def format_duration(seconds: int) -> str:
    """Human-readable countdown for a status label."""
    seconds = max(0, int(seconds))
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes:02}:{secs:02}"
