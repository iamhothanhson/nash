from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from config import settings
from app.portfolio.capital_tracker import VirtualAccount
from app.portfolio import runtime_balance as runtime_balance_mod
from app.portfolio.runtime_balance import (
    entry_balance_kwargs,
    get_runtime_account_state,
    uses_exchange_balance,
)


def test_uses_exchange_balance_live_and_demo() -> None:
    assert uses_exchange_balance("live") is True
    assert uses_exchange_balance("demo") is True
    assert uses_exchange_balance("backtest") is False


def test_live_and_demo_share_exchange_metrics_path() -> None:
    virtual = VirtualAccount(50.0)
    metrics = {
        "total_margin_balance": 200.0,
        "total_wallet_balance": 195.0,
        "available_balance": 72.5,
        "open_notional": 310.0,
    }
    client = MagicMock()
    client.get_account_metrics.return_value = metrics
    engine = SimpleNamespace(_client=client)

    for mode in ("live", "demo"):
        settings.MODE = mode
        state = get_runtime_account_state(engine, virtual)
        assert state["risk_balance"] == 200.0
        assert state["available_balance"] == 72.5
        assert state["open_notional"] == 310.0

    kwargs = entry_balance_kwargs(engine, virtual)
    assert kwargs["account_balance"] == 200.0
    assert kwargs["available_balance"] == 72.5
    assert kwargs["open_notional_total"] == 310.0
