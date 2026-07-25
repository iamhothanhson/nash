from __future__ import annotations

from backtesting.config import SLIPPAGE_BPS
from backtesting.models import BacktestPosition


def calculate_pnl(
    pos: BacktestPosition,
    qty: float,
    exit_price: float,
) -> float:
    if pos.direction == "LONG":
        return qty * (exit_price - pos.entry)
    return qty * (pos.entry - exit_price)


def apply_slippage(price: float, is_long: bool) -> float:
    multiplier = (
        1 - SLIPPAGE_BPS / 10000
        if is_long
        else 1 + SLIPPAGE_BPS / 10000
    )
    return price * multiplier
