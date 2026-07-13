
from __future__ import annotations

from dataclasses import dataclass

from app.setup_builder.models import Direction, SetupType, StrategyFamily
from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

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
