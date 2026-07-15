from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StopLossData:
    price: float
    percent: float
    risk_usdt: float | None
    sl_order_id: int | None
    sl_hit: bool


@dataclass
class TakeProfitLevel:
    price: float
    percent: float
    partial_close: float
    hit: bool
    order_id: int | None


@dataclass
class RuntimePosition:
    status: str
    symbol: str
    side: str
    strategy: str
    setup: str
    size_usdt: float
    margin_usdt: float
    entry: float
    entry_qty: float
    pos_side: str | None
    stop_loss: StopLossData
    take_profit: list[TakeProfitLevel]
    pnl_usdt: float
    exchange_pnl_usdt: float | None
    balance_usdt: float
    closed_reason: str | None
    opened: str
    closed: str | None
