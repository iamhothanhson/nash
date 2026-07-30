
from typing import Any, Literal

from dataclasses import dataclass
from app.setup_builder.models import Direction, SetupType, StrategyFamily


@dataclass(frozen=True)
class TrailingStopConfig:
    type: Literal["atr"]
    atr_mult: float
    atr_value: float = 0.0


@dataclass(frozen=True)
class TradeSignal:
    symbol: str
    direction: Direction
    entry: float
    stop_loss: float
    tp1: float
    tp1_r: float = 0.0
    tp1_pct: float = 0.0
    trailing_stop: TrailingStopConfig | None = None
    setup_score: int = 0
    setup_type: SetupType = ""
    strategy_family: StrategyFamily = ""
    confirmation_mode: str = ""
    setup_grade: str = ""
    market_structure: str = "None"
    confidence: float = 0.0
    rsi: float | None = None
    atr: float | None = None
    volatility: float | None = None
    ema_slope: float | None = None
    trend_phase: str | None = None
    market_state: Any | None = None
    features: dict | None = None