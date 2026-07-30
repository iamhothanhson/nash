from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from market_analyzer.market_state import MarketState
from app.core.constants import BREAKOUT, PULLBACK


class SetupType(str, Enum):
    BREAKOUT = BREAKOUT
    PULLBACK = PULLBACK


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"

StrategyFamily = str

@dataclass
class Setup:
    symbol: str
    entry: float
    setup_type: SetupType
    side: Optional[Direction]
    score: float
    grade: str
    market_state: MarketState
    features: dict[str, Any]
    timestamp: int
    config: dict[str, Any]
    strategy_family: str = ""
    anchor: float = 0.0
    trade_allowed: bool = False

@dataclass(frozen=True)
class ScoreResult:
    score: float