from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import main
from app.config import settings
from app.position_management.staged import ManagedPosition

pytestmark = pytest.mark.unit


def _short_pos(*, entry: float = 269.88, qty: float = 1.04) -> ManagedPosition:
    return ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=qty,
        qty_open=qty,
        entry=entry,
        stop_loss=272.0,
        tp1=265.0,
        tp2=262.0,
        tp3=260.0,
        open_time_iso=datetime.now(timezone.utc).isoformat(),
        initial_risk_usd=2.0,
        max_hard_stop_loss_usd=2.2,
    )


def test_sync_position_from_exchange_updates_entry_and_qty() -> None:
    pos = _short_pos(entry=269.88, qty=1.04)
    client = MagicMock()
    client.get_position_risk_snapshot.return_value = {
        "position_amt": -1.038,
        "entry_price": 272.41,
    }
    client.get_user_trades.return_value = [
        {"side": "SELL", "qty": "1.038", "time": int(datetime.now(timezone.utc).timestamp() * 1000)},
    ]
    engine = MagicMock(_client=client)
    old_mode = settings.MODE
    settings.MODE = "live"
    try:
        ok = main._sync_position_from_exchange(engine, pos, plan_entry=269.88)
    finally:
        settings.MODE = old_mode
    assert ok is True
    assert pos.entry == pytest.approx(272.41, rel=0, abs=1e-6)
    assert pos.qty_open == pytest.approx(1.038, rel=0, abs=1e-6)
    assert pos.initial_risk_usd > 0.0


def test_sync_position_from_exchange_skips_side_mismatch() -> None:
    pos = _short_pos()
    pos.direction = "LONG"
    client = MagicMock()
    client.get_position_risk_snapshot.return_value = {"position_amt": -1.0, "entry_price": 270.0}
    engine = MagicMock(_client=client)
    old_mode = settings.MODE
    settings.MODE = "demo"
    try:
        ok = main._sync_position_from_exchange(engine, pos)
    finally:
        settings.MODE = old_mode
    assert ok is False
    assert pos.entry == pytest.approx(269.88)
