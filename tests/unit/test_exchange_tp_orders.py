from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.exchange_tp_orders import (
    TP2_ORDER_KIND_TAKE_PROFIT_MARKET,
    ensure_exchange_tp2_after_tp1,
    normalize_exchange_tp2_order_kind,
    place_tp2_limit_after_tp1,
    place_tp_limit_orders_after_entry,
    resolve_tp2_order_qty,
)
from position_management.staged import ManagedPosition


def test_place_tp_limit_orders_at_entry_places_tp1_only() -> None:
    client = MagicMock()
    client.use_hedge_position_side.return_value = False
    client.get_position_amount.return_value = 10.0
    client.normalize_qty.side_effect = lambda _s, q: float(q)
    client.create_reduce_only_limit_order.return_value = {"orderId": 101}

    meta = place_tp_limit_orders_after_entry(
        client,
        symbol="RENDERUSDT",
        entry_side="BUY",
        total_qty=10.0,
        tp1=2.07,
        tp2=2.11,
        tp1_close_frac=0.5,
        tp2_close_frac=0.3,
    )

    assert meta["placed"] is True
    assert meta["tp1_order_id"] == 101
    assert meta["tp2_order_id"] is None
    assert client.create_reduce_only_limit_order.call_count == 1
    c1 = client.create_reduce_only_limit_order.call_args_list[0]
    assert c1[0][1] == "SELL"
    assert c1[0][2] == 5.0
    assert c1[0][3] == 2.07


def test_resolve_tp2_order_qty_from_original_total() -> None:
    client = MagicMock()
    client.normalize_qty.side_effect = lambda _s, q: float(q)
    q2 = resolve_tp2_order_qty(
        symbol="RENDERUSDT",
        qty_total=10.0,
        qty_open=5.0,
        tp2_close_frac=0.3,
        client=client,
    )
    assert q2 == 3.0


def test_place_tp2_limit_after_tp1() -> None:
    client = MagicMock()
    client.use_hedge_position_side.return_value = False
    client.normalize_qty.side_effect = lambda _s, q: float(q)
    client.create_conditional_take_profit_market_order.return_value = {"algoId": 202}
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="SHORT",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.647,
        stop_loss=1.669,
        tp1=1.622,
        tp2=1.606,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.3,
    )
    meta = place_tp2_limit_after_tp1(client, pos)
    assert meta["placed"] is True
    assert meta["tp2_order_id"] == 202
    assert meta["tp2_order_kind"] == TP2_ORDER_KIND_TAKE_PROFIT_MARKET
    assert meta["tp2_qty"] == pytest.approx(3.6)
    c1 = client.create_conditional_take_profit_market_order.call_args
    assert c1[0][1] == "BUY"
    assert c1[0][2] == pytest.approx(3.6)
    assert c1[0][3] == 1.606


def test_ensure_exchange_tp2_after_tp1_sets_order_id(monkeypatch) -> None:
    monkeypatch.setattr(
        "execution.exchange_tp_orders.exchange_tp_orders_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "execution.exchange_tp_orders.exchange_tp2_after_tp1_enabled",
        lambda: True,
    )
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="SHORT",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.647,
        stop_loss=1.669,
        tp1=1.622,
        tp2=1.606,
        tp3=0.0,
        hit_tp1=True,
        exchange_tp_orders_placed=True,
        tp2_close_frac=0.3,
    )
    client = MagicMock()
    client.use_hedge_position_side.return_value = False
    client.normalize_qty.side_effect = lambda _s, q: float(q)
    client.create_conditional_take_profit_market_order.return_value = {"algoId": 303}
    engine = MagicMock(_client=client)

    assert ensure_exchange_tp2_after_tp1(engine, pos) is True
    assert pos.exchange_tp2_order_id == 303
    assert pos.exchange_tp2_order_kind == TP2_ORDER_KIND_TAKE_PROFIT_MARKET


def test_place_tp2_after_tp1_surfaces_placement_error() -> None:
    client = MagicMock()
    client.use_hedge_position_side.return_value = False
    client.normalize_qty.side_effect = lambda _s, q: float(q)
    client.create_conditional_take_profit_market_order.side_effect = RuntimeError("algo down")
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="SHORT",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.647,
        stop_loss=1.669,
        tp1=1.622,
        tp2=1.606,
        tp3=0.0,
        hit_tp1=True,
        tp2_close_frac=0.3,
    )
    meta = place_tp2_limit_after_tp1(client, pos)
    assert meta["placed"] is False
    assert meta["tp2_order_id"] is None
    assert "algo down" in meta["errors"][0]


def test_normalize_exchange_tp2_order_kind() -> None:
    assert (
        normalize_exchange_tp2_order_kind("CONDITIONAL TAKE_PROFIT_MARKET")
        == TP2_ORDER_KIND_TAKE_PROFIT_MARKET
    )
    assert normalize_exchange_tp2_order_kind("conditional") == TP2_ORDER_KIND_TAKE_PROFIT_MARKET
    assert normalize_exchange_tp2_order_kind("limit") == TP2_ORDER_KIND_TAKE_PROFIT_MARKET
    assert normalize_exchange_tp2_order_kind("") == ""
