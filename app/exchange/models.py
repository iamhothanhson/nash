from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict


class OHLCVRecord(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float

@dataclass(frozen=True, slots=True)
class AccountState:
    wallet_balance: Decimal
    available_balance: Decimal
    margin_balance: Decimal
    unrealized_pnl: Decimal
