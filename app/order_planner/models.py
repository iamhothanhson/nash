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
    tp1_qty: float                 # Quantity to close at TP1
    tp2_qty: float                 # Quantity to close at TP2
    tp3_qty: float  
    qty: float
    notional: float
    risk_amount: float
    risk_percent: float
    setup_type: str
    setup_grade: str
    setup_score: float
    confirmation_mode: str
    strategy_family: str
    r_multiple: float
    tp1_qty: float = 0.0
    tp2_qty: float = 0.0
    tp3_qty: float = 0.0
    market_structure: str = "None"
    market_regime_detail: Any | None = None