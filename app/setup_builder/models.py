from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from market_analyzer.market_state import MarketState
from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK, LIQUIDITY_SWEEP


class SetupType(str, Enum):
    BREAKOUT = BREAKOUT
    BREAKOUT_RETEST = BREAKOUT_RETEST
    PULLBACK = PULLBACK
    LIQUIDITY_SWEEP = LIQUIDITY_SWEEP


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


SetupGrade = str
StrategyFamily = str

@dataclass
class Setup:
    symbol: str
    timestamp: int
    setup_type: SetupType
    side: Optional[Side]
    grade: str
    score: float
    market_state: MarketState
    features: dict[str, Any]
    anchor: float = 0.0
    confidence: float = 0.0
    trade_allowed: bool = False