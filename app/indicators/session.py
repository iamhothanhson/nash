from __future__ import annotations

from datetime import datetime


def detect_session(timestamp: datetime) -> str:
    h = timestamp.hour
    if h < 8:
        return "ASIA"
    if h < 16:
        return "EU"
    return "US"
