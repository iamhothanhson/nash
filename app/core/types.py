from enum import Enum
from typing import Literal

Direction = Literal["LONG", "SHORT"]


class TrendDirection(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class MarketRegime(str, Enum):
    STRONG_BULLISH = "STRONG_BULLISH"
    BULLISH = "BULLISH"
    WEAK_BULLISH = "WEAK_BULLISH"
    RANGE = "RANGE"
    WEAK_BEARISH = "WEAK_BEARISH"
    BEARISH = "BEARISH"
    STRONG_BEARISH = "STRONG_BEARISH"
    HIGH_VOLATILITY_CHOP = "HIGH_VOLATILITY_CHOP"


class MarketStructure(str, Enum):
    HHHL = "HHHL"
    LHLL = "LHLL"
    RANGE = "RANGE"
    UNKNOWN = "UNKNOWN"