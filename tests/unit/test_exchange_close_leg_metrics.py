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
from app.monitoring.messages import format_fill_pnl_usdt
from app.position_management.staged import ManagedPosition
from app.reconciliation.exchange_trades import trade_net_realized_pnl_usdt

pytestmark = pytest.mark.unit


def _pos(*, open_ms: int | None = None) -> ManagedPosition:
    if open_ms is None:
        open_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000
    open_iso = datetime.fromtimestamp(open_ms / 1000.0, tz=timezone.utc).isoformat()
    return ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=1.0,
        qty_open=0.5,
        entry=250.0,
        stop_loss=248.0,
        tp1=252.0,
        tp2=255.0,
        tp3=258.0,
        open_time_iso=open_iso,
    )


def test_exchange_close_leg_metrics_sums_partial_and_watermark() -> None:
    open_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000
    tp1_trade = {"side": "SELL", "qty": "0.5", "price": "252", "realizedPnl": "1.10", "time": open_ms + 5_000}
    tp2_trade = {"side": "SELL", "qty": "0.3", "price": "255", "realizedPnl": "0.90", "time": open_ms + 15_000}
    client = MagicMock()
    client.get_user_trades.side_effect = [
        [tp1_trade],
        [tp1_trade, tp2_trade],
    ]
    engine = MagicMock(_client=client)
    pos = _pos(open_ms=open_ms)

    with patch.object(main.time, "sleep", lambda _s: None):
        snap1 = main._exchange_close_leg_metrics(engine, pos, target_qty=0.5, after_trade_ms=None)
    assert snap1 is not None
    assert snap1["realized_pnl_usdt"] == pytest.approx(1.10)
    assert snap1["end_trade_ms"] == float(open_ms + 5_000)
    main._apply_exchange_trade_watermark(pos, snap1)

    with patch.object(main.time, "sleep", lambda _s: None):
        snap2 = main._exchange_close_leg_metrics(
            engine, pos, target_qty=0.3, after_trade_ms=pos.last_exchange_trade_ms
        )
    assert snap2 is not None
    assert snap2["realized_pnl_usdt"] == pytest.approx(0.90)
    assert snap2["end_trade_ms"] == float(open_ms + 15_000)


def test_exchange_journal_close_metrics_full_position_qty() -> None:
    open_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000
    trades = [
        {"side": "SELL", "qty": "0.5", "price": "252", "realizedPnl": "1.0", "time": open_ms + 5_000},
        {"side": "SELL", "qty": "0.5", "price": "258", "realizedPnl": "2.0", "time": open_ms + 15_000},
    ]
    client = MagicMock()
    client.get_user_trades.return_value = trades
    engine = MagicMock(_client=client)
    pos = _pos(open_ms=open_ms)

    with patch.object(main.time, "sleep", lambda _s: None):
        snap = main._exchange_journal_close_metrics(engine, pos)
    assert snap is not None
    assert snap["realized_pnl_usdt"] == pytest.approx(3.0)


def test_trade_net_realized_pnl_subtracts_usdt_commission() -> None:
    row = {
        "realizedPnl": "1.10",
        "commission": "0.08",
        "commissionAsset": "USDT",
    }
    assert trade_net_realized_pnl_usdt(row) == pytest.approx(1.02)


def test_exchange_close_leg_metrics_uses_net_after_commission() -> None:
    open_ms = int(datetime.now(timezone.utc).timestamp() * 1000) - 60_000
    trade = {
        "side": "SELL",
        "qty": "0.5",
        "price": "252",
        "realizedPnl": "1.10",
        "commission": "0.10",
        "commissionAsset": "USDT",
        "time": open_ms + 5_000,
    }
    client = MagicMock()
    client.get_user_trades.return_value = [trade]
    engine = MagicMock(_client=client)
    pos = _pos(open_ms=open_ms)

    with patch.object(main.time, "sleep", lambda _s: None):
        snap = main._exchange_close_leg_metrics(engine, pos, target_qty=0.5, after_trade_ms=None)
    assert snap is not None
    assert snap["realized_pnl_usdt"] == pytest.approx(1.0)


def test_format_fill_pnl_usdt_includes_exchange() -> None:
    assert format_fill_pnl_usdt(1.65) == "PNL: +1.65 USDT"
    assert format_fill_pnl_usdt(1.65, 1.63) == "PNL: +1.65 USDT | Exchange PNL: +1.63 USDT"
