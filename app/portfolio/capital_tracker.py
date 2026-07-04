from __future__ import annotations

import os
from dataclasses import dataclass, field

from config import settings


def positions_open_notional(positions: list) -> float:
    total = 0.0
    for p in positions:
        total += float(getattr(p, "qty_open", 0)) * float(getattr(p, "entry", 0))
    return total


def positions_open_margin(positions: list) -> float:
    lev = max(1.0, float(settings.LEVERAGE))
    return positions_open_notional(positions) / lev


def portfolio_available_balance(
    virtual: VirtualAccount,
    positions: list | None = None,
) -> float:
    """Free margin for new entries: wallet balance minus margin locked in open positions."""
    lev = max(1.0, float(settings.LEVERAGE))
    if positions is not None:
        locked = positions_open_margin(positions)
    else:
        locked = float(virtual.open_notional) / lev
    return max(0.0, float(virtual.balance) - locked)


@dataclass
class VirtualAccount:
    initial_capital: float
    balance: float = field(init=False)
    open_notional: float = 0.0

    def __post_init__(self) -> None:
        self.balance = max(0.0, float(self.initial_capital))

    def max_exposure_limit(self) -> float:
        return self.balance * float(settings.TOTAL_EXPOSURE_MULTIPLIER)

    def record_open(self, notional: float) -> None:
        self.open_notional += max(0.0, float(notional))

    def apply_realized_pnl(self, pnl: float, notional_released: float) -> None:
        self.open_notional = max(0.0, self.open_notional - max(0.0, float(notional_released)))
        self.balance += float(pnl)
        self.balance = max(0.0, self.balance)

