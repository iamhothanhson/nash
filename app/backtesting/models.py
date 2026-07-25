from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal


Direction = Literal["LONG", "SHORT"]
ExitReason = Literal["STOP_LOSS", "TP1", "TP2", "TP3", "END_OF_BACKTEST"]


@dataclass
class BacktestPosition:
    # Identity
    position_id: str = ""
    symbol: str = ""
    direction: Direction = "LONG"

    # Strategy
    strategy_family: str = ""
    setup_type: str | None = None
    setup_score: float = 0.0
    setup_grade: str = "SKIP"

    # Entry
    entry_time: datetime | None = None
    entry: float = 0.0
    initial_qty: float = 0.0
    remaining_qty: float = 0.0

    # Risk
    stop_loss: float = 0.0
    risk_amount: float = 0.0
    margin_usdt: float = 0.0
    leverage: int = 0

    # Take Profit
    take_profits: list[TakeProfit]
    sl_hit: bool = False

    # Runtime
    status: str = "Open"
    realized_pnl: float = 0.0
    pnl_usdt: float = 0.0
    exchange_pnl_usdt: float | None = None
    balance_usdt: float = 0.0

    opened: datetime | None = None
    closed: datetime | None = None
    closed_reason: str | None = None

    # Exchange
    pos_side: str | None = None
    sl_order_id: str | None = None
    tp1_order_id: str | None = None
    tp2_order_id: str | None = None
    tp3_order_id: str | None = None


@dataclass
class TakeProfit:
    level: int
    price: float
    qty: float
    hit: bool = False
    trail_to: float | None = None

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
    setup_grade: str = ""
    risk_amount: float = 0.0


@dataclass
class EquityPoint:
    timestamp: datetime
    balance: float
    unrealized_pnl: float
    equity: float