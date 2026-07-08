from __future__ import annotations

from dataclasses import dataclass

from market_analyzer import feature


@dataclass(frozen=True)
class SetupCandidate:
    setup_type: str
    direction: str
    anchor: float
    key_level_points: int
    confirmation_points: int
    trigger_type: str
    features: dict
    confidence: float = 0.0
    debug_reason: str | None = None

