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


@dataclass
class TrendBarContext:
    phase: str
    exhaustion_risk: float
    compression_quality: float
    atr_spike_ratio: float
    impulse_streak: int
    extended_trend: bool
    compression_gate_ok: bool
