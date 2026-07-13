
from dataclasses import dataclass
from app.setup_builder.models import SetupType, Side, StrategyFamily

@dataclass(frozen=True)
class TradeSignal:
    direction: Side
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
    market_structure: str = "None"
    market_regime_detail: dict | None = None
    confidence: float = 0.0
    rsi: float | None = None
    atr: float | None = None
    volatility: float | None = None
    ema_slope: float | None = None
    trend_phase: str | None = None
    tp1_r: float = 0.0
    tp2_r: float = 0.0