from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from market_analyzer.models import SetupFeatures


class TrendDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class MarketRegime(str, Enum):
    STRONG_BULLISH = "strong_bullish"
    BULLISH = "bullish"
    WEAK_BULLISH = "weak_bullish"
    RANGE = "range"
    WEAK_BEARISH = "weak_bearish"
    BEARISH = "bearish"
    STRONG_BEARISH = "strong_bearish"
    HIGH_VOLATILITY_CHOP = "high_volatility_chop"


class MarketStructure(str, Enum):
    HHHL = "HHHL"
    LHLL = "LHLL"
    RANGE = "Range"
    UNKNOWN = "Unknown"


@dataclass(slots=True, frozen=True)
class MarketState:
    symbol: str
    timestamp: int
    timeframe: str
    trend_direction: TrendDirection
    trend_aligned: bool
    regime: MarketRegime
    structure: MarketStructure
    regime_confidence: float
    is_trending: bool
    is_ranging: bool
    is_high_volatility: bool
    indicators: dict | None = None
    data_5m: object | None = None
    data_15m: object | None = None
    data_1h: object | None = None