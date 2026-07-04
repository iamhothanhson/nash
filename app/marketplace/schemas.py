from __future__ import annotations

from typing import TypedDict


class OHLCVRecord(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float
