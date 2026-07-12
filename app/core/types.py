from enum import Enum
from typing import Literal

Direction = Literal["LONG", "SHORT"]


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