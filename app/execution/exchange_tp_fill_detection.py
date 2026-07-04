"""Detect TP1/TP2 hits from exchange order status (live/demo)."""

from __future__ import annotations

from typing import Any, Callable

from coins.loader import price_rounding_decimal
from common.rounding import format_price
from execution.exchange_client import BinanceOrderError
from execution.exchange_tp_orders import exchange_tp_detect_by_order_status_enabled
from monitoring.logger import log as daily_log
from position_management.post_tp1_stop import apply_post_tp1_stop_on_first_hit
from position_management.staged import (
    ExitFill,
    ManagedPosition,
    _init_runner_trail,
    is_runner_tp3,
    tp1_on_exchange,
    tp2_on_exchange,
)


def _order_status_filled(order: dict[str, Any]) -> bool:
    return str(order.get("status", "")).strip().upper() == "FILLED"


def _order_executed_qty(order: dict[str, Any]) -> float:
    for key in ("executedQty", "cumQty"):
        try:
            q = float(order.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            q = 0.0
        if q > 1e-12:
            return q
    try:
        return max(0.0, float(order.get("origQty", 0.0) or 0.0))
    except (TypeError, ValueError):
        return 0.0


def _order_avg_price(order: dict[str, Any], fallback: float) -> float:
    for key in ("avgPrice", "price", "actualPrice", "triggerPrice"):
        try:
            px = float(order.get(key, 0.0) or 0.0)
        except (TypeError, ValueError):
            px = 0.0
        if px > 0.0:
            return px
    return float(fallback)


def _tp_status_log_prefix(tag: str | None) -> str:
    if str(tag or "").strip().upper() == "TP2 HIT":
        return "[TP2 FILL]"
    return "[TP1 FILL]"


def _sync_qty_open_from_exchange(
    client: Any,
    pos: ManagedPosition,
    *,
    tag: str | None = None,
) -> bool:
    if not hasattr(client, "get_position_risk_snapshot"):
        return False
    try:
        snap = client.get_position_risk_snapshot(pos.symbol)
    except Exception as exc:
        prefix = _tp_status_log_prefix(tag)
        daily_log(f"{prefix} {pos.symbol} | positionRisk sync failed | {exc}")
        return False
    amt = float(snap.get("position_amt", 0.0))
    if abs(amt) <= 1e-12:
        pos.qty_open = 0.0
        pos.closed = True
        return True
    ex_dir = "LONG" if amt > 0.0 else "SHORT"
    if str(pos.direction).upper() != ex_dir:
        return False
    ex_qty = abs(float(amt))
    pos.qty_open = ex_qty
    pos.qty_total = max(float(pos.qty_total), ex_qty, float(pos.qty_open))
    pos.last_sent_qty_open = float(pos.qty_open)
    return True


def _normalize_algo_order_for_fill(algo: dict[str, Any]) -> dict[str, Any]:
    """Map Binance conditional algo payload to regular order status fields."""
    algo_status = str(algo.get("algoStatus", "")).strip().upper()
    try:
        actual_qty = float(algo.get("actualQty", 0) or 0)
    except (TypeError, ValueError):
        actual_qty = 0.0
    try:
        planned_qty = float(algo.get("quantity", 0) or 0)
    except (TypeError, ValueError):
        planned_qty = 0.0
    try:
        actual_price = float(algo.get("actualPrice", 0) or 0)
    except (TypeError, ValueError):
        actual_price = 0.0
    try:
        trigger_price = float(algo.get("triggerPrice", 0) or 0)
    except (TypeError, ValueError):
        trigger_price = 0.0
    try:
        limit_price = float(algo.get("price", 0) or 0)
    except (TypeError, ValueError):
        limit_price = 0.0

    if algo_status == "FINISHED" and actual_qty > 1e-12:
        status = (
            "PARTIALLY_FILLED"
            if planned_qty > 1e-12 and actual_qty < planned_qty - 1e-12
            else "FILLED"
        )
    elif algo_status in ("TRIGGERED", "TRIGGERING") and actual_qty > 1e-12:
        status = (
            "PARTIALLY_FILLED"
            if planned_qty > 1e-12 and actual_qty < planned_qty - 1e-12
            else "FILLED"
        )
    elif algo_status in ("CANCELED", "EXPIRED"):
        status = algo_status
    else:
        status = "NEW"

    out = dict(algo)
    out["status"] = status
    out["executedQty"] = actual_qty if actual_qty > 0 else 0.0
    out["avgPrice"] = actual_price if actual_price > 0 else (limit_price or trigger_price)
    out["price"] = limit_price or trigger_price
    out["origQty"] = planned_qty
    return out


def _query_tp1_order(
    client: Any,
    sym_u: str,
    order_id: int,
    *,
    tag: str | None = None,
) -> dict[str, Any] | None:
    oid = int(order_id)
    prefix = _tp_status_log_prefix(tag)
    if not hasattr(client, "get_futures_order"):
        return None
    try:
        return client.get_futures_order(sym_u, oid)
    except BinanceOrderError as exc:
        daily_log(f"{prefix} {sym_u} | order query failed orderId={oid} | {exc}")
        return None
    except Exception as exc:
        daily_log(f"{prefix} {sym_u} | order query failed orderId={oid} | {exc}")
        return None


def _query_tp2_take_profit_market_order(
    client: Any,
    sym_u: str,
    order_id: int,
    *,
    tag: str | None = None,
) -> dict[str, Any] | None:
    """Fetch TP2 TAKE_PROFIT_MARKET only via GET /fapi/v1/algoOrder?algoId=."""
    oid = int(order_id)
    prefix = _tp_status_log_prefix(tag)
    fetch = getattr(client, "get_tp2_take_profit_market_algo_order", None)
    if fetch is None:
        fetch = lambda algo_id: client.get_futures_algo_order(algo_id)
    try:
        return _normalize_algo_order_for_fill(fetch(oid))
    except BinanceOrderError as exc:
        daily_log(f"{prefix} {sym_u} | Algo order query failed algoId={oid} | {exc}")
        return None
    except Exception as exc:
        daily_log(f"{prefix} {sym_u} | Algo order query failed algoId={oid} | {exc}")
        return None


def _build_tp1_fill_from_order(
    pos: ManagedPosition,
    order: dict[str, Any],
    *,
    qty_open_before: float,
    now_ts: float | None,
    pnl_fn: Callable[..., float],
) -> ExitFill | None:
    if pos.hit_tp1 or pos.qty_open <= 0:
        return None
    target_tp1 = float(pos.qty_total) * float(pos.tp1_close_frac)
    min_expected = min(target_tp1 * 0.5, target_tp1 - 1e-8)
    leg = _order_executed_qty(order)
    if leg <= 1e-12 or leg < min_expected:
        leg = max(0.0, float(qty_open_before) - float(pos.qty_open))
    if leg <= 1e-12 or leg < min_expected:
        leg = min(target_tp1, float(qty_open_before))
    rem = max(0.0, float(pos.qty_open))
    px = _order_avg_price(order, float(pos.tp1))
    pnl = float(pnl_fn(pos.direction, pos.entry, px, leg))
    pos.realized_pnl += pnl
    pos.tp1_hit_at_ts = float(now_ts) if now_ts is not None else pos.tp1_hit_at_ts
    apply_post_tp1_stop_on_first_hit(pos)
    return ExitFill("TP1 HIT", px, leg, rem, pnl)


def _build_tp2_fill_from_order(
    pos: ManagedPosition,
    order: dict[str, Any],
    *,
    qty_open_before: float,
    now_ts: float | None,
    pnl_fn: Callable[..., float],
    df15: Any = None,
) -> ExitFill | None:
    if pos.hit_tp2 or not pos.hit_tp1 or pos.qty_open <= 0:
        return None
    target_tp2 = float(pos.qty_total) * float(pos.tp2_close_frac)
    min_expected = min(target_tp2 * 0.5, target_tp2 - 1e-8)
    leg = _order_executed_qty(order)
    if leg <= 1e-12 or leg < min_expected:
        leg = max(0.0, float(qty_open_before) - float(pos.qty_open))
    if leg <= 1e-12 or leg < min_expected:
        leg = min(target_tp2, float(qty_open_before))
    rem = max(0.0, float(pos.qty_open))
    px = _order_avg_price(order, float(pos.tp2))
    pnl = float(pnl_fn(pos.direction, pos.entry, px, leg))
    pos.realized_pnl += pnl
    pos.hit_tp2 = True
    pos.tp2_hit_at_ts = float(now_ts) if now_ts is not None else pos.tp2_hit_at_ts
    if is_runner_tp3(pos.tp3):
        _init_runner_trail(pos, df15=df15, bar_ts=now_ts)
    return ExitFill("TP2 HIT", px, leg, rem, pnl)


def _process_tp_order_fill(
    pos: ManagedPosition,
    client: Any,
    order_id: int,
    *,
    tag: str,
    now_ts: float | None,
    pnl_fn: Callable[..., float],
    df15: Any = None,
) -> ExitFill | None:
    sym_u = str(pos.symbol).strip().upper()
    if tag == "TP1 HIT":
        order = _query_tp1_order(client, sym_u, order_id, tag=tag)
    else:
        order = _query_tp2_take_profit_market_order(client, sym_u, order_id, tag=tag)
    if order is None or not _order_status_filled(order):
        return None
    exec_q = _order_executed_qty(order)
    avg_px = _order_avg_price(order, float(pos.tp1 if tag == "TP1 HIT" else pos.tp2))
    prefix = _tp_status_log_prefix(tag)
    daily_log(
        f"{prefix} {sym_u} | {tag} | orderId={int(order_id)} status=FILLED | "
        f"executedQty={exec_q:.8g} avgPrice={format_price(avg_px, price_rounding_decimal(sym_u))}"
    )
    qty_before = float(pos.qty_open)
    _sync_qty_open_from_exchange(client, pos, tag=tag)
    if tag == "TP1 HIT":
        return _build_tp1_fill_from_order(
            pos, order, qty_open_before=qty_before, now_ts=now_ts, pnl_fn=pnl_fn
        )
    return _build_tp2_fill_from_order(
        pos,
        order,
        qty_open_before=qty_before,
        now_ts=now_ts,
        pnl_fn=pnl_fn,
        df15=df15,
    )


def collect_fills_from_exchange_tp_orders(
    engine: Any,
    pos: ManagedPosition,
    *,
    now_ts: float | None = None,
    pnl_fn: Callable[..., float],
    df15: Any = None,
) -> list[ExitFill]:
    """
    When TP limit orders are on the exchange, detect FILLED status and emit TP fills.

    Bar-touch TP detection is skipped for those legs (see ``apply_staged_management``).
    """
    if not exchange_tp_detect_by_order_status_enabled():
        return []
    if pos.closed or float(pos.qty_open) <= 0:
        return []
    client = getattr(engine, "_client", None)
    if client is None:
        return []

    out: list[ExitFill] = []
    oid1 = getattr(pos, "exchange_tp1_order_id", None)
    if oid1 is not None and tp1_on_exchange(pos) and not pos.hit_tp1:
        fill = _process_tp_order_fill(
            pos,
            client,
            int(oid1),
            tag="TP1 HIT",
            now_ts=now_ts,
            pnl_fn=pnl_fn,
        )
        if fill is not None:
            out.append(fill)

    oid2 = getattr(pos, "exchange_tp2_order_id", None)
    if oid2 is not None and tp2_on_exchange(pos) and pos.hit_tp1 and not pos.hit_tp2:
        fill = _process_tp_order_fill(
            pos,
            client,
            int(oid2),
            tag="TP2 HIT",
            now_ts=now_ts,
            pnl_fn=pnl_fn,
            df15=df15,
        )
        if fill is not None:
            out.append(fill)

    return out
