from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SetupCandidate:
    setup_type: str
    direction: str
    anchor: float
    trigger_type: str
    features: dict
    detected_at: int
    timeframe: str

