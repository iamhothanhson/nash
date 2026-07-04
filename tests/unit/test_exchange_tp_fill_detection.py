from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.exchange_client import BinanceOrderError
from execution.exchange_tp_fill_detection import (
    _normalize_algo_order_for_fill,
    collect_fills_from_exchange_tp_orders,
)
from position_management.staged import ManagedPosition

pytestmark = pytest.mark.unit


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def test_collect_tp1_fill_when_order_status_filled(monkeypatch) -> None:
    logged: list[str] = []
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.daily_log",
        lambda msg: logged.append(str(msg)),
    )
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.exchange_tp_detect_by_order_status_enabled",
        lambda: True,
    )
    pos = ManagedPosition(
        symbol="FETUSDT",
        direction="LONG",
        qty_total=100.0,
        qty_open=100.0,
        entry=0.20,
        stop_loss=0.19,
        current_stop_loss=0.19,
        tp1=0.21,
        tp2=0.22,
        tp3=0.0,
        exchange_tp1_order_id=101,
    )
    client = MagicMock()

    def _order_status(_sym: str, order_id: int) -> dict:
        if int(order_id) == 101:
            return {
                "status": "FILLED",
                "executedQty": "50",
                "avgPrice": "0.2105",
            }
        return {"status": "NEW", "executedQty": "0", "avgPrice": "0"}

    client.get_futures_order.side_effect = _order_status
    client.get_position_risk_snapshot.return_value = {
        "position_amt": 50.0,
        "entry_price": 0.20,
    }
    engine = MagicMock(_client=client)

    fills = collect_fills_from_exchange_tp_orders(
        engine, pos, now_ts=1_700_000.0, pnl_fn=_pnl
    )

    assert len(fills) == 1
    assert fills[0].tag == "TP1 HIT"
    assert fills[0].qty_closed == 50.0
    assert fills[0].qty_remaining == 50.0
    assert pos.hit_tp1
    assert pos.exchange_tp1_order_id == 101
    assert client.get_futures_order.call_args_list[0] == (("FETUSDT", 101),)
    assert client.get_futures_order.call_count >= 1
    assert any("[TP1 FILL] FETUSDT | TP1 HIT | orderId=101 status=FILLED" in line for line in logged)


def test_no_fill_when_order_still_new(monkeypatch) -> None:
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.exchange_tp_detect_by_order_status_enabled",
        lambda: True,
    )
    pos = ManagedPosition(
        symbol="FETUSDT",
        direction="LONG",
        qty_total=100.0,
        qty_open=100.0,
        entry=0.20,
        stop_loss=0.19,
        current_stop_loss=0.19,
        tp1=0.21,
        tp2=0.22,
        tp3=0.0,
        exchange_tp1_order_id=101,
    )
    client = MagicMock()
    client.get_futures_order.return_value = {"status": "NEW", "executedQty": "0"}
    engine = MagicMock(_client=client)

    fills = collect_fills_from_exchange_tp_orders(
        engine, pos, now_ts=1_700_000.0, pnl_fn=_pnl
    )

    assert fills == []
    assert not pos.hit_tp1


def test_normalize_algo_order_finished_maps_to_filled() -> None:
    normalized = _normalize_algo_order_for_fill(
        {
            "algoStatus": "FINISHED",
            "quantity": "0.044",
            "actualQty": "0.044",
            "actualPrice": "204.75",
            "triggerPrice": "204.74771",
        }
    )
    assert normalized["status"] == "FILLED"
    assert normalized["executedQty"] == pytest.approx(0.044)
    assert normalized["avgPrice"] == pytest.approx(204.75)


def test_collect_tp2_fill_via_take_profit_market_algo_order(monkeypatch) -> None:
    logged: list[str] = []
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.daily_log",
        lambda msg: logged.append(str(msg)),
    )
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.exchange_tp_detect_by_order_status_enabled",
        lambda: True,
    )
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=0.147,
        qty_open=0.074,
        entry=208.45,
        stop_loss=210.90,
        current_stop_loss=208.24,
        tp1=205.98,
        tp2=204.75,
        tp3=0.0,
        hit_tp1=True,
        exchange_tp2_order_id=1000001920449341,
        exchange_tp2_order_kind="take_profit_market",
    )
    client = MagicMock()
    client.get_tp2_take_profit_market_algo_order.return_value = {
        "algoStatus": "FINISHED",
        "quantity": "0.044",
        "actualQty": "0.044",
        "actualPrice": "204.75",
        "triggerPrice": "204.74771",
    }
    client.get_position_risk_snapshot.return_value = {
        "position_amt": -0.03,
        "entry_price": 208.45,
    }
    engine = MagicMock(_client=client)

    fills = collect_fills_from_exchange_tp_orders(
        engine, pos, now_ts=1_700_000.0, pnl_fn=_pnl
    )

    assert len(fills) == 1
    assert fills[0].tag == "TP2 HIT"
    assert fills[0].qty_closed == pytest.approx(0.044)
    assert pos.hit_tp2
    client.get_futures_order.assert_not_called()
    client.get_tp2_take_profit_market_algo_order.assert_called_once_with(
        1000001920449341
    )
    assert any(
        "[TP2 FILL] TAOUSDT | TP2 HIT | orderId=1000001920449341 status=FILLED" in line
        for line in logged
    )


def test_collect_tp2_no_fill_when_algo_order_still_new(monkeypatch) -> None:
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.exchange_tp_detect_by_order_status_enabled",
        lambda: True,
    )
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=0.147,
        qty_open=0.074,
        entry=208.45,
        stop_loss=210.90,
        current_stop_loss=208.24,
        tp1=205.98,
        tp2=204.75,
        tp3=0.0,
        hit_tp1=True,
        exchange_tp2_order_id=1000001920449341,
    )
    client = MagicMock()
    client.get_tp2_take_profit_market_algo_order.return_value = {
        "algoStatus": "NEW",
        "quantity": "0.044",
        "actualQty": "0",
        "actualPrice": "0",
        "triggerPrice": "204.74771",
    }
    engine = MagicMock(_client=client)

    fills = collect_fills_from_exchange_tp_orders(
        engine, pos, now_ts=1_700_000.0, pnl_fn=_pnl
    )

    assert fills == []
    assert not pos.hit_tp2
    client.get_futures_order.assert_not_called()


def test_collect_tp2_take_profit_market_no_fallback_on_algo_miss(monkeypatch) -> None:
    logged: list[str] = []
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.daily_log",
        lambda msg: logged.append(str(msg)),
    )
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.exchange_tp_detect_by_order_status_enabled",
        lambda: True,
    )
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=5000.0,
        qty_open=2671.0,
        entry=1.62,
        stop_loss=1.58,
        current_stop_loss=1.62,
        tp1=1.63,
        tp2=1.643,
        tp3=0.0,
        hit_tp1=True,
        exchange_tp2_order_id=1000000103616477,
    )
    client = MagicMock()
    client.get_tp2_take_profit_market_algo_order.side_effect = BinanceOrderError(
        status_code=400,
        code=-2013,
        msg="Order does not exist.",
        request_params={"algoId": "1000000103616477"},
    )
    engine = MagicMock(_client=client)

    fills = collect_fills_from_exchange_tp_orders(
        engine, pos, now_ts=1_700_000.0, pnl_fn=_pnl
    )

    assert fills == []
    assert not pos.hit_tp2
    client.get_open_algo_orders.assert_not_called()
    client.get_all_algo_orders.assert_not_called()
    client.get_futures_order.assert_not_called()
    assert any("Algo order query failed algoId=1000000103616477" in line for line in logged)


def test_tp2_status_logs_algo_query_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.exchange_tp_detect_by_order_status_enabled",
        lambda: True,
    )
    logged: list[str] = []
    monkeypatch.setattr(
        "execution.exchange_tp_fill_detection.daily_log",
        lambda msg: logged.append(str(msg)),
    )
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=0.147,
        qty_open=0.074,
        entry=208.45,
        stop_loss=210.90,
        current_stop_loss=208.24,
        tp1=205.98,
        tp2=204.75,
        tp3=0.0,
        hit_tp1=True,
        exchange_tp2_order_id=1000001920449341,
    )
    client = MagicMock()
    client.get_tp2_take_profit_market_algo_order.side_effect = RuntimeError("algo down")
    engine = MagicMock(_client=client)

    fills = collect_fills_from_exchange_tp_orders(
        engine, pos, now_ts=1_700_000.0, pnl_fn=_pnl
    )

    assert fills == []
    assert any("[TP2 FILL]" in line for line in logged)
    assert any("Algo order query failed algoId=1000001920449341" in line for line in logged)
    client.get_futures_order.assert_not_called()
