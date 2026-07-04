from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from position_management import stop_exchange_sync as stop_sync_mod
from position_management.staged import ManagedPosition, apply_staged_management
from position_management.stop_exchange_sync import (
    _needs_resync,
    exchange_stop_is_active,
    runner_stop_qty_for_exchange,
    update_stop_on_exchange,
)


class _QtyClient:
    def normalize_qty(self, _sym: str, qty: float) -> float:
        return float(qty)

    def normalize_stop_price(self, _sym: str, stop: float) -> float:
        return round(float(stop), 2)

    def price_tick_size(self, _sym: str) -> float:
        return 0.01

    def lot_size_step(self, _sym: str) -> float:
        return 1.0


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def test_needs_resync_skips_when_sent_stop_only_differs_by_tick_rounding() -> None:
    client = _QtyClient()
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=0.117,
        qty_open=0.117,
        entry=220.0,
        stop_loss=213.82,
        current_stop_loss=213.82666533981214,
        tp1=225.0,
        tp2=230.0,
        tp3=0.0,
        stop_exchange_order_id=1000001916066591,
        last_sent_stop_loss=213.82666533981214,
        last_sent_qty_open=0.117,
    )
    n_stop = client.normalize_stop_price("TAOUSDT", float(pos.current_stop_loss))
    assert _needs_resync(pos, client, "TAOUSDT", n_stop, 0.117) is False


def test_needs_resync_when_stop_moves_beyond_tick() -> None:
    client = _QtyClient()
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=0.117,
        qty_open=0.117,
        entry=220.0,
        stop_loss=213.82,
        current_stop_loss=214.0,
        tp1=225.0,
        tp2=230.0,
        tp3=0.0,
        stop_exchange_order_id=1000001916066591,
        last_sent_stop_loss=213.82666533981214,
        last_sent_qty_open=0.117,
    )
    n_stop = client.normalize_stop_price("TAOUSDT", float(pos.current_stop_loss))
    assert _needs_resync(pos, client, "TAOUSDT", n_stop, 0.117) is True


def test_runner_stop_qty_full_runner_when_exchange_tp2_disabled(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.EXCHANGE_TP2_AFTER_TP1", False)
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.657,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
        exchange_tp2_order_id=999,
    )
    qty = runner_stop_qty_for_exchange(pos, _QtyClient(), "RENDERUSDT")
    assert qty == pytest.approx(6.0)


def test_runner_stop_qty_keeps_full_runner_with_tp2_resting() -> None:
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.657,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
        exchange_tp2_order_id=999,
    )
    client = _QtyClient()
    qty = runner_stop_qty_for_exchange(pos, client, "RENDERUSDT")
    assert qty == pytest.approx(6.0)


def test_update_stop_skips_new_sl_move_after_tp3(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    cleaned: list[str] = []

    def _cleanup(_client, pos: ManagedPosition, *, reason: str) -> None:
        cleaned.append(reason)
        pos.stop_exchange_order_id = None
        pos.last_sent_stop_loss = 0.0
        pos.last_sent_qty_open = 0.0

    monkeypatch.setattr(stop_sync_mod, "cancel_orders_for_flat_position_if_live", _cleanup)

    class _Client(_QtyClient):
        def create_conditional_stop_market_order(self, *args, **kwargs):  # pragma: no cover
            raise AssertionError("should not place a stop after TP3")

    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=10.0,
        qty_open=2.0,
        entry=263.91,
        stop_loss=266.82,
        current_stop_loss=263.62,
        tp1=261.0,
        tp2=259.54,
        tp3=0.0,
        hit_tp1=True,
        hit_tp2=True,
        hit_tp3=True,
        stop_exchange_order_id=1001,
        last_sent_stop_loss=263.62,
        last_sent_qty_open=2.0,
    )

    assert update_stop_on_exchange(pos, _Client())
    assert cleaned == ["stop_sync_tp3"]
    assert pos.stop_exchange_order_id is None
    assert pos.last_sent_stop_loss == 0.0
    assert pos.last_sent_qty_open == 0.0


def test_exchange_stop_is_active_when_synced(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.657,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
        exchange_tp2_order_id=999,
        stop_exchange_order_id=1001,
        last_sent_stop_loss=1.657,
        last_sent_qty_open=6.0,
    )
    assert exchange_stop_is_active(pos, _QtyClient()) is True


def test_post_tp1_be_uses_close_position_with_tp2_resting(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    monkeypatch.setattr("position_management.stop_exchange_sync.time.sleep", lambda _seconds: None)

    class _StopClient(_QtyClient):
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def normalize_stop_price(self, _sym: str, stop: float) -> float:
            return float(stop)

        def use_hedge_position_side(self) -> bool:
            return False

        def create_conditional_stop_market_order(
            self,
            symbol: str,
            side: str,
            stop_price: float,
            *,
            quantity: float | None = None,
            close_position: bool = False,
            position_side: str | None = None,
            cancel_all_algo_orders: bool = True,
        ) -> dict:
            self.calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "stop_price": stop_price,
                    "quantity": quantity,
                    "close_position": close_position,
                    "position_side": position_side,
                    "cancel_all_algo_orders": cancel_all_algo_orders,
                }
            )
            return {"orderId": 4321}

    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.656655,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
        exchange_tp2_order_id=999,
    )
    client = _StopClient()

    assert update_stop_on_exchange(pos, client)
    assert client.calls[-1]["close_position"] is True
    assert client.calls[-1]["quantity"] is None
    assert pos.stop_exchange_order_id == 4321
    assert pos.last_sent_qty_open == pytest.approx(6.0)


def test_post_tp1_be_uses_close_position_when_qty_rounding_differs(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    monkeypatch.setattr("position_management.stop_exchange_sync.time.sleep", lambda _seconds: None)

    class _RoundedStopClient(_QtyClient):
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def normalize_qty(self, _sym: str, qty: float) -> float:
            return int(float(qty))

        def normalize_stop_price(self, _sym: str, stop: float) -> float:
            return float(stop)

        def use_hedge_position_side(self) -> bool:
            return False

        def create_conditional_stop_market_order(
            self,
            symbol: str,
            side: str,
            stop_price: float,
            *,
            quantity: float | None = None,
            close_position: bool = False,
            position_side: str | None = None,
            cancel_all_algo_orders: bool = True,
        ) -> dict:
            self.calls.append(
                {
                    "symbol": symbol,
                    "side": side,
                    "stop_price": stop_price,
                    "quantity": quantity,
                    "close_position": close_position,
                    "position_side": position_side,
                    "cancel_all_algo_orders": cancel_all_algo_orders,
                }
            )
            return {"orderId": 4322}

    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=13.2,
        qty_open=6.6,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.656655,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
        exchange_tp2_order_id=999,
    )
    client = _RoundedStopClient()

    assert update_stop_on_exchange(pos, client)
    assert client.calls[-1]["close_position"] is True
    assert client.calls[-1]["quantity"] is None
    assert pos.stop_exchange_order_id == 4322
    assert pos.last_sent_qty_open == pytest.approx(6.6)


def test_post_tp1_be_falls_back_to_qty_when_close_position_rejected(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    monkeypatch.setattr("position_management.stop_exchange_sync.time.sleep", lambda _seconds: None)

    from execution.exchange_client import BinanceOrderError

    class _RejectClosePositionClient(_QtyClient):
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def normalize_stop_price(self, _sym: str, stop: float) -> float:
            return float(stop)

        def use_hedge_position_side(self) -> bool:
            return False

        def create_conditional_stop_market_order(
            self,
            symbol: str,
            side: str,
            stop_price: float,
            *,
            quantity: float | None = None,
            close_position: bool = False,
            position_side: str | None = None,
            cancel_all_algo_orders: bool = True,
        ) -> dict:
            self.calls.append(
                {
                    "close_position": close_position,
                    "quantity": quantity,
                }
            )
            if close_position:
                raise BinanceOrderError(
                    status_code=400,
                    code=-4509,
                    msg="Time in Force (TIF) GTE can only be used with open positions.",
                    request_params={"symbol": symbol},
                )
            return {"orderId": 4509}

    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=0.14,
        qty_open=0.07,
        entry=208.0,
        stop_loss=210.41,
        current_stop_loss=207.79,
        tp1=204.99,
        tp2=203.53,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
    )
    client = _RejectClosePositionClient()

    assert update_stop_on_exchange(pos, client)
    assert len(client.calls) == 2
    assert client.calls[0]["close_position"] is True
    assert client.calls[1]["close_position"] is False
    assert client.calls[1]["quantity"] == pytest.approx(0.07)
    assert pos.stop_exchange_order_id == 4509
    assert pos.last_sent_qty_open == pytest.approx(0.07)


def test_staged_skips_memory_sl_when_exchange_stop_active(monkeypatch) -> None:
    monkeypatch.setattr("position_management.staged.settings.MODE", "live")
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.657,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        stop_exchange_order_id=1001,
        last_sent_stop_loss=1.657,
        last_sent_qty_open=6.0,
    )
    fills = apply_staged_management(
        pos,
        high=1.68,
        low=1.65,
        pnl_fn=_pnl,
    )
    assert not any(f.tag == "SL HIT" for f in fills)
    assert pos.qty_open == 6.0
    assert not pos.closed


def test_update_stop_skips_dust_runner_cancels_existing_stop(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.POSITION_DUST_CLOSE_ENABLED", True)
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.POSITION_DUST_CLOSE_NOTIONAL_USDT", 7.0)
    monkeypatch.setattr("position_management.stop_exchange_sync.time.sleep", lambda _seconds: None)

    class _DustClient(_QtyClient):
        def __init__(self) -> None:
            self.canceled: list[int] = []
            self.placed = False

        def get_mark_price(self, _sym: str) -> float:
            return 205.0

        def use_hedge_position_side(self) -> bool:
            return False

        def cancel_futures_stop_order(self, _sym: str, order_id: int) -> None:
            self.canceled.append(int(order_id))

        def create_conditional_stop_market_order(self, *args, **kwargs) -> dict:
            self.placed = True
            return {"orderId": 999}

    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=0.075,
        qty_open=0.001,
        entry=208.0,
        stop_loss=210.41,
        current_stop_loss=207.79,
        tp1=204.99,
        tp2=203.53,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.30,
        stop_exchange_order_id=111,
        last_sent_stop_loss=207.79,
        last_sent_qty_open=0.074,
    )
    client = _DustClient()

    assert update_stop_on_exchange(pos, client) is True
    assert client.canceled == [111]
    assert client.placed is False
    assert pos.stop_exchange_order_id is None
    assert pos.last_sent_stop_loss == 0.0
    assert pos.last_sent_qty_open == 0.0


def test_exchange_stop_inactive_for_dust_runner(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.POSITION_DUST_CLOSE_ENABLED", True)
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.POSITION_DUST_CLOSE_NOTIONAL_USDT", 7.0)

    class _DustClient(_QtyClient):
        def get_mark_price(self, _sym: str) -> float:
            return 205.0

    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=0.075,
        qty_open=0.001,
        entry=208.0,
        stop_loss=210.41,
        current_stop_loss=207.79,
        tp1=204.99,
        tp2=203.53,
        tp3=0.0,
        hit_tp1=True,
        stop_exchange_order_id=111,
        last_sent_stop_loss=207.79,
        last_sent_qty_open=0.074,
    )
    assert exchange_stop_is_active(pos, _DustClient()) is False


def test_post_tp2_exchange_sl_placed_sends_telegram(monkeypatch) -> None:
    monkeypatch.setattr("position_management.stop_exchange_sync.settings.MODE", "demo")
    monkeypatch.setattr("position_management.stop_exchange_sync.time.sleep", lambda _seconds: None)
    alerts: list[str] = []
    monkeypatch.setattr(
        "position_management.stop_exchange_sync.send_alert",
        lambda msg: alerts.append(str(msg)) or True,
    )

    class _TrailStopClient(_QtyClient):
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def normalize_stop_price(self, _sym: str, stop: float) -> float:
            return round(float(stop), 3)

        def use_hedge_position_side(self) -> bool:
            return False

        def cancel_futures_stop_order(self, _sym: str, order_id: int) -> None:
            return None

        def create_conditional_stop_market_order(
            self,
            symbol: str,
            side: str,
            stop_price: float,
            *,
            quantity: float | None = None,
            close_position: bool = False,
            position_side: str | None = None,
            cancel_all_algo_orders: bool = True,
        ) -> dict:
            self.calls.append(
                {
                    "close_position": close_position,
                    "quantity": quantity,
                }
            )
            return {"orderId": 1000001925761069}

    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.6,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.568,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
        hit_tp2=True,
        tp2_close_frac=0.30,
        exchange_tp2_order_id=999,
        stop_exchange_order_id=1001,
        last_sent_stop_loss=1.656655,
        last_sent_qty_open=6.6,
    )
    client = _TrailStopClient()

    assert update_stop_on_exchange(pos, client)
    assert client.calls[-1]["close_position"] is False
    assert client.calls[-1]["quantity"] == pytest.approx(6.6)
    assert len(alerts) == 1
    assert alerts[0] == (
        "[SL MOVE] RENDERUSDT | Placed Conditional Stop Loss orderId=1000001925761069 "
        "Price=1.568 Size USDT: 10.92"
    )
