from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal


Direction = Literal["LONG", "SHORT"]
ExitReason = Literal["STOP_LOSS", "TP1", "TP2", "TP3", "END_OF_BACKTEST"]


@dataclass
class BacktestPosition:
    symbol: str
    direction: Direction

    entry_time: datetime
    entry: float
    stop_loss: float

    tp1: float
    tp2: float
    tp3: float

    initial_qty: float
    remaining_qty: float

    tp1_qty: float
    tp2_qty: float
    tp3_qty: float

    risk_amount: float
    setup_type: str | None = None
    setup_score: float = 0.0

    tp1_hit: bool = False
    tp2_hit: bool = False
    tp3_hit: bool = False

    realized_pnl: float = 0.0

    order_plan: Any | None = None


@dataclass
class BacktestTrade:
    symbol: str
    direction: Direction

    entry_time: datetime
    exit_time: datetime

    entry_price: float
    exit_price: float

    qty: float
    pnl: float
    fee: float
    net_pnl: float

    exit_reason: ExitReason

    setup_type: str | None = None
    setup_score: float = 0.0
    risk_amount: float = 0.0


@dataclass
class EquityPoint:
    timestamp: datetime
    balance: float
    unrealized_pnl: float
    equity: float
