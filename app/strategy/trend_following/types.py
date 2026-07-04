
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK
from strategy.models import SetupCandidate, TrendBarContext  # noqa: F401


def clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def normalize_tf_confidence(rsi_signal: float, rsi_tf: float, rsi: float,
                             slope_factor: float = 0.5, rsi_consistency: float = 0.7) -> float:
    c1 = 1.0 - abs(rsi_signal - 50.0) / 50.0 * slope_factor
    c2 = 1.0 - abs(rsi_tf - 50.0) / 50.0 * rsi_consistency
    c3 = 1.0 - abs(rsi - 50.0) / 50.0 * max(0.0, 1.0 - rsi_consistency)
    return (c1 + c2 + c3) / 3.0


Direction = Literal["LONG", "SHORT"]
SetupType = Literal["breakout", "pullback", "breakout_retest"]
SetupGrade = Literal["A+", "A"]
StrategyFamily = Literal["trend_following"]

SETUP_PRIORITY: dict[str, int] = {BREAKOUT: 2, BREAKOUT_RETEST: 2, PULLBACK: 1}

@dataclass(frozen=True)
class TradeSignal:
    direction: Direction
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    setup_score: int
    signal_risk_per_trade: float
    setup_type: SetupType
    setup_grade: SetupGrade
    strategy_family: StrategyFamily
    r_multiple: float
    confirmation_mode: str
    market_structure: str = "Range"
    market_regime_detail: dict | None = None
    confidence: float = 0.0
    rsi: float | None = None
    atr: float | None = None
    volatility: float | None = None
    ema_slope: float | None = None
    trend_phase: str | None = None
