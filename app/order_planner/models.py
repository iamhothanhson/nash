from dataclasses import dataclass
from typing import Any

@dataclass(slots=True)
class OrderPlan:
    symbol: str
    direction: str
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    qty: float
    tp1_qty: float
    tp2_qty: float
    tp3_qty: float
    notional: float
    risk_amount: float
    risk_percent: float
    risk_per_trade: float
    setup_type: str
    setup_score: float
    confirmation_mode: str
    strategy_family: str
    risk_multiplier: float
    market_structure: str = "None"
    market_regime_detail: Any | None = None