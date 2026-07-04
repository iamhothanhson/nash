from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from config import settings
from portfolio.capital_tracker import (
    VirtualAccount,
    portfolio_available_balance,
    positions_open_margin,
    positions_open_notional,
)


class _Pos:
    def __init__(self, qty_open: float, entry: float) -> None:
        self.qty_open = qty_open
        self.entry = entry


def test_portfolio_available_balance_subtracts_open_margin() -> None:
    vacct = VirtualAccount(100.0)
    positions = [_Pos(qty_open=1.0, entry=50.0)]
    notional = positions_open_notional(positions)
    vacct.record_open(notional)
    assert positions_open_margin(positions) == notional / max(1.0, float(settings.LEVERAGE))
    available = portfolio_available_balance(vacct, positions)
    expected = 100.0 - positions_open_margin(positions)
    assert abs(available - expected) < 1e-6


def test_portfolio_available_balance_zero_when_fully_allocated() -> None:
    lev = max(1.0, float(settings.LEVERAGE))
    vacct = VirtualAccount(100.0)
    notional = 100.0 * lev
    vacct.record_open(notional)
    available = portfolio_available_balance(vacct)
    assert available == 0.0
