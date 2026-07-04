from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.cancel_position_orders import (
    cancel_all_orders_for_flat_position,
    clear_position_exchange_order_state,
)
from position_management.staged import ManagedPosition


class _CleanupClient:
    def __init__(self, *, flat: bool = True, hedge: bool = False) -> None:
        self.flat = flat
        self.hedge = hedge
        self.canceled_limit: list[int] = []
        self.canceled_protective: list[int] = []
        self.algo_swept = False

    def use_hedge_position_side(self) -> bool:
        return self.hedge

    def get_position_amount(self, _sym: str, _leg: str | None = None) -> float:
        return 0.0 if self.flat else 1.0

    def has_open_position_size(self, _sym: str) -> bool:
        return not self.flat

    def cancel_futures_order(self, _sym: str, order_id: int) -> dict:
        self.canceled_limit.append(int(order_id))
        return {"orderId": int(order_id)}

    def cancel_futures_stop_order(self, _sym: str, order_id: int) -> dict:
        self.canceled_protective.append(int(order_id))
        return {"algoId": int(order_id)}

    def cancel_all_open_algo_orders(self, _sym: str) -> dict:
        self.algo_swept = True
        return {}


@pytest.mark.unit
def test_cancel_all_orders_for_flat_position_cancels_known_ids_and_sweeps(monkeypatch) -> None:
    monkeypatch.setattr("execution.cancel_position_orders.settings.MODE", "live")
    client = _CleanupClient(flat=True)
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=0.2,
        qty_open=0.0,
        entry=208.0,
        stop_loss=205.0,
        current_stop_loss=208.41,
        tp1=210.0,
        tp2=212.0,
        tp3=0.0,
        closed=True,
        stop_exchange_order_id=1001,
        exchange_tp1_order_id=2001,
        exchange_tp2_order_id=3001,
        exchange_tp2_order_kind="take_profit_market",
    )

    result = cancel_all_orders_for_flat_position(client, pos, reason="HARD STOP")

    assert result.canceled_tp1 == 2001
    assert result.canceled_tp2 == 3001
    assert result.canceled_sl == 1001
    assert result.algo_sweep is True
    assert client.canceled_limit == [2001]
    assert client.canceled_protective == [3001, 1001]
    assert client.algo_swept is True
    assert pos.stop_exchange_order_id is None
    assert pos.exchange_tp1_order_id is None
    assert pos.exchange_tp2_order_id is None
    assert pos.exchange_tp2_order_kind == ""


@pytest.mark.unit
def test_cancel_skips_algo_sweep_when_position_not_flat(monkeypatch) -> None:
    monkeypatch.setattr("execution.cancel_position_orders.settings.MODE", "live")
    client = _CleanupClient(flat=False)
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=0.2,
        qty_open=0.0,
        entry=208.0,
        stop_loss=205.0,
        current_stop_loss=208.41,
        tp1=210.0,
        tp2=212.0,
        tp3=0.0,
        closed=True,
        stop_exchange_order_id=1001,
    )

    result = cancel_all_orders_for_flat_position(client, pos, reason="SL HIT")

    assert result.canceled_sl == 1001
    assert result.algo_sweep is False
    assert client.algo_swept is False


@pytest.mark.unit
def test_clear_position_exchange_order_state_only_runtime() -> None:
    pos = ManagedPosition(
        symbol="FETUSDT",
        direction="LONG",
        qty_total=1.0,
        qty_open=0.0,
        entry=0.2,
        stop_loss=0.19,
        current_stop_loss=0.2,
        tp1=0.21,
        tp2=0.22,
        tp3=0.0,
        stop_exchange_order_id=11,
        exchange_tp1_order_id=22,
        exchange_tp2_order_id=33,
        exchange_tp2_order_kind="take_profit_market",
        last_sent_stop_loss=0.2,
        last_sent_qty_open=1.0,
    )
    clear_position_exchange_order_state(pos)
    assert pos.stop_exchange_order_id is None
    assert pos.exchange_tp1_order_id is None
    assert pos.exchange_tp2_order_id is None
    assert pos.exchange_tp2_order_kind == ""
    assert pos.last_sent_stop_loss == 0.0
    assert pos.last_sent_qty_open == 0.0
