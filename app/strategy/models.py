from __future__ import annotations

from dataclasses import dataclass

from market_analyzer import feature


@dataclass(frozen=True)
class SetupCandidate:
    setup_type: str
    direction: str
    anchor: float
    trigger_type: str
    features: dict
    detected_at: int
    timeframe: str

