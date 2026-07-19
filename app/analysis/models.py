from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class MarketStateSnapshot:
    regime: str
    trend_direction: str
    trend_aligned: bool
    regime_confidence: float
    market_structure: str

    is_trending: bool
    is_ranging: bool
    is_high_volatility: bool


@dataclass(slots=True)
class IndicatorSnapshot:
    ema_slope_15m: float
    ema_slope_1h: float

    adx_15m: float
    adx_1h: float

    atr_percent: float
    atr_percentile: float

    rsi: float
    volume_ratio: float


@dataclass(slots=True)
class SetupFeatureSnapshot:
    setup_score: float
    confirmation_mode: str

    breakout_strength_pct: float
    distance_from_level_pct: float

    candle_body_ratio: float
    wick_ratio: float

    touch_count: int
    breakout_level_age: int

    htf_confirmed: bool


@dataclass(slots=True)
class EntrySnapshot:
    # Trade identity
    symbol: str
    side: str
    strategy_setup: str

    # Snapshot time
    captured_at: datetime

    # Three analysis blocks
    market_state: MarketStateSnapshot
    indicators: IndicatorSnapshot
    setup_features: SetupFeatureSnapshot
    indicators_raw: Any = None

    # Extra trade context
    context: dict[str, Any] = field(default_factory=dict)