"""Binance userTrades attribution for closes and partial legs."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from execution.execution_engine import ExecutionEngine
from monitoring.logger import log
from position_management.staged import ManagedPosition


def close_side_for_position(direction: str) -> str:
    return "SELL" if str(direction).upper() == "LONG" else "BUY"


def entry_side_for_position(direction: str) -> str:
    return "BUY" if str(direction).upper() == "LONG" else "SELL"


def ms_from_iso(value: str) -> int | None:
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() * 1000)


def iso_from_ms(value: int | float | str | None) -> str:
    try:
        ms = int(float(value or 0))
    except (TypeError, ValueError):
        ms = 0
    if ms <= 0:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def trade_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def trade_net_realized_pnl_usdt(row: dict[str, Any]) -> float:
    gross = trade_float(row, "realizedPnl", 0.0)
    asset = str(row.get("commissionAsset", "USDT") or "USDT").strip().upper()
    if asset not in ("", "USDT"):
        return float(gross)
    commission = abs(trade_float(row, "commission", 0.0))
    return float(gross) - float(commission)


def apply_exchange_trade_watermark(pos: ManagedPosition, snap: dict[str, float]) -> None:
    end_ms = int(float(snap.get("end_trade_ms", 0.0) or 0.0))
    if end_ms > 0:
        pos.last_exchange_trade_ms = max(int(getattr(pos, "last_exchange_trade_ms", 0) or 0), end_ms)


def exchange_journal_balance_usdt(engine: ExecutionEngine) -> float | None:
    mode = str(settings.MODE).strip().lower()
    if mode not in ("live", "demo"):
        return None
    client = getattr(engine, "_client", None)
    if client is None or not hasattr(client, "get_account_metrics"):
        return None
    try:
        m = client.get_account_metrics()
        v = float(m.get("total_wallet_balance") or m.get("total_margin_balance") or 0.0)
        return max(0.0, v)
    except Exception:
        return None


def stop_trigger_time_for_position(
    client: Any,
    pos: ManagedPosition,
    *,
    start_ms: int | None,
    end_ms: int | None,
) -> int | None:
    stop_oid = getattr(pos, "stop_exchange_order_id", None)
    if stop_oid is None or not hasattr(client, "get_all_algo_orders"):
        return None
    try:
        orders = client.get_all_algo_orders(
            pos.symbol,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=100,
        )
    except Exception as exc:
        log(f"[RECONCILE CLOSE] {pos.symbol} | failed algo history lookup | {exc}")
        return None
    for row in orders:
        if not isinstance(row, dict):
            continue
        oid = row.get("algoId") or row.get("orderId")
        if str(oid) != str(stop_oid):
            continue
        trigger_time = row.get("triggerTime")
        try:
            ts = int(float(trigger_time or 0))
        except (TypeError, ValueError):
            return None
        return ts if ts > 0 else None
    return None


def exchange_close_leg_metrics(
    engine: ExecutionEngine,
    pos: ManagedPosition,
    *,
    target_qty: float,
    after_trade_ms: int | None = None,
) -> dict[str, float] | None:
    client = getattr(engine, "_client", None)
    if client is None or not hasattr(client, "get_user_trades"):
        return None
    opened_ms = ms_from_iso(pos.open_time_iso)
    if opened_ms is None:
        opened_ms = int(time.time() * 1000) - 86_400_000
    wall_end = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = max(0, opened_ms - 120_000)
    if after_trade_ms is not None and int(after_trade_ms) > 0:
        start_ms = max(start_ms, int(after_trade_ms) + 1)
    end_ms = wall_end + 180_000
    close_side = close_side_for_position(pos.direction)
    trade_floor_ms = max(opened_ms - 10_000, int(after_trade_ms or 0))

    rows: list[dict[str, Any]] = []
    for _ in range(6):
        try:
            trades = client.get_user_trades(
                pos.symbol,
                start_time_ms=start_ms,
                end_time_ms=end_ms,
                limit=1000,
            )
        except Exception:
            trades = []
        rows = []
        if isinstance(trades, list):
            for row in trades:
                if not isinstance(row, dict):
                    continue
                if str(row.get("side", "")).upper() != close_side:
                    continue
                trade_ms = int(trade_float(row, "time", 0.0))
                if trade_ms < trade_floor_ms or trade_ms > wall_end + 120_000:
                    continue
                rows.append(row)
        if rows:
            break
        time.sleep(0.55)
    if not rows:
        return None

    tgt = max(float(target_qty), 1e-12)
    picked: list[dict[str, Any]] = []
    acc_qty = 0.0
    for row in sorted(rows, key=lambda r: int(trade_float(r, "time", 0.0)), reverse=True):
        q = abs(trade_float(row, "qty", 0.0))
        if q <= 1e-12:
            continue
        picked.append(row)
        acc_qty += q
        if acc_qty + 1e-9 >= tgt:
            break
    if not picked:
        alt = [r for r in rows if abs(trade_float(r, "qty", 0.0)) > 1e-12]
        if not alt:
            return None
        loose_qty = sum(abs(trade_float(r, "qty", 0.0)) for r in alt)
        loose_pnl = sum(trade_net_realized_pnl_usdt(r) for r in alt)
        if loose_qty <= 1e-12:
            return None
        notional = sum(abs(trade_float(r, "qty", 0.0)) * trade_float(r, "price", 0.0) for r in alt)
        end_ms = max(int(trade_float(r, "time", 0.0)) for r in alt)
        return {
            "avg_close_price": float(notional / loose_qty),
            "realized_pnl_usdt": float(loose_pnl),
            "end_trade_ms": float(end_ms),
        }

    qty_sum = sum(abs(trade_float(r, "qty", 0.0)) for r in picked)
    if qty_sum <= 1e-12:
        return None
    notional = sum(abs(trade_float(r, "qty", 0.0)) * trade_float(r, "price", 0.0) for r in picked)
    realized = sum(trade_net_realized_pnl_usdt(r) for r in picked)
    end_ms = max(int(trade_float(r, "time", 0.0)) for r in picked)
    return {
        "avg_close_price": float(notional / qty_sum),
        "realized_pnl_usdt": float(realized),
        "end_trade_ms": float(end_ms),
    }


def exchange_partial_close_metrics(
    engine: ExecutionEngine,
    pos: ManagedPosition,
    *,
    target_qty: float,
) -> dict[str, float] | None:
    after_ms = int(getattr(pos, "last_exchange_trade_ms", 0) or 0)
    return exchange_close_leg_metrics(
        engine,
        pos,
        target_qty=float(target_qty),
        after_trade_ms=after_ms if after_ms > 0 else None,
    )


def fetch_exchange_partial_fill_leg(
    engine: ExecutionEngine,
    pos: ManagedPosition,
    *,
    target_qty: float,
) -> dict[str, float] | None:
    snap = exchange_partial_close_metrics(engine, pos, target_qty=float(target_qty))
    if snap is None:
        time.sleep(0.4)
        snap = exchange_partial_close_metrics(engine, pos, target_qty=float(target_qty))
    if snap is None:
        return None
    apply_exchange_trade_watermark(pos, snap)
    return snap


def exchange_journal_close_metrics(
    engine: ExecutionEngine,
    pos: ManagedPosition,
) -> dict[str, float] | None:
    return exchange_close_leg_metrics(
        engine,
        pos,
        target_qty=max(float(pos.qty_total), 1e-12),
        after_trade_ms=None,
    )


def resolve_flat_close_fill(
    engine: ExecutionEngine, pos: ManagedPosition
) -> dict[str, float | str | bool]:
    """Attribute remaining qty close from exchange trades; always returns a fill dict."""
    fill = _exchange_flat_close_fill_primary(engine, pos)
    if fill is not None:
        return fill
    log(
        f"[RECONCILE CLOSE] {pos.symbol} | exchange flat but close fill not found | "
        f"local_qty={float(pos.qty_open):.8f} | journaling fallback"
    )
    return _exchange_flat_close_fallback_fill(engine, pos)


def _exchange_flat_close_fallback_fill(
    engine: ExecutionEngine, pos: ManagedPosition
) -> dict[str, float | str | bool]:
    rem_qty = max(0.0, float(pos.qty_open))
    exit_px = float(pos.current_stop_loss or pos.stop_loss or pos.entry)
    leg_pnl = 0.0
    close_iso = datetime.now(timezone.utc).isoformat()
    after_ms = int(getattr(pos, "last_exchange_trade_ms", 0) or 0)
    if rem_qty > 1e-12:
        snap = exchange_close_leg_metrics(
            engine,
            pos,
            target_qty=rem_qty,
            after_trade_ms=after_ms if after_ms > 0 else None,
        )
        if snap is not None:
            leg_pnl = float(snap["realized_pnl_usdt"])
            exit_px = float(snap["avg_close_price"])
            close_iso = iso_from_ms(int(float(snap.get("end_trade_ms", 0.0) or 0.0)))
            apply_exchange_trade_watermark(pos, snap)
    is_stop = False
    client = getattr(engine, "_client", None)
    if client is not None and rem_qty > 1e-12:
        opened_ms = ms_from_iso(pos.open_time_iso)
        start_ms = max(0, opened_ms - 60_000) if opened_ms is not None else None
        end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        close_ms = int(ms_from_iso(close_iso)) if close_iso else end_ms
        stop_trigger_ms = stop_trigger_time_for_position(
            client,
            pos,
            start_ms=start_ms,
            end_ms=end_ms,
        )
        if stop_trigger_ms is not None:
            is_stop = abs(int(stop_trigger_ms) - int(close_ms)) <= 5_000
    return {
        "price": float(exit_px),
        "qty": float(rem_qty if rem_qty > 1e-12 else pos.qty_total),
        "pnl": float(leg_pnl),
        "time_iso": str(close_iso),
        "is_stop": is_stop,
        "trigger_price": float(pos.current_stop_loss or pos.stop_loss or pos.entry),
    }


def _exchange_flat_close_fill_primary(
    engine: ExecutionEngine, pos: ManagedPosition
) -> dict[str, float | str | bool] | None:
    client = getattr(engine, "_client", None)
    if client is None or not hasattr(client, "get_user_trades"):
        return None
    rem_qty = max(0.0, float(pos.qty_open))
    after_ms = int(getattr(pos, "last_exchange_trade_ms", 0) or 0)
    if rem_qty > 1e-12:
        snap = exchange_close_leg_metrics(
            engine,
            pos,
            target_qty=rem_qty,
            after_trade_ms=after_ms if after_ms > 0 else None,
        )
        if snap is None:
            time.sleep(0.4)
            snap = exchange_close_leg_metrics(
                engine,
                pos,
                target_qty=rem_qty,
                after_trade_ms=after_ms if after_ms > 0 else None,
            )
        if snap is not None:
            opened_ms = ms_from_iso(pos.open_time_iso)
            start_ms = max(0, opened_ms - 60_000) if opened_ms is not None else None
            end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
            close_ms = int(float(snap.get("end_trade_ms", 0.0) or 0.0))
            stop_trigger_ms = stop_trigger_time_for_position(
                client,
                pos,
                start_ms=start_ms,
                end_ms=end_ms,
            )
            is_stop = stop_trigger_ms is not None and abs(int(stop_trigger_ms) - close_ms) <= 5_000
            apply_exchange_trade_watermark(pos, snap)
            return {
                "price": float(snap["avg_close_price"]),
                "qty": float(rem_qty),
                "pnl": float(snap["realized_pnl_usdt"]),
                "time_iso": iso_from_ms(close_ms),
                "is_stop": bool(is_stop),
                "trigger_price": float(pos.current_stop_loss or pos.stop_loss or pos.entry),
            }
    opened_ms = ms_from_iso(pos.open_time_iso)
    start_ms = max(0, opened_ms - 60_000) if opened_ms is not None else None
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    try:
        trades = client.get_user_trades(
            pos.symbol,
            start_time_ms=start_ms,
            end_time_ms=end_ms,
            limit=1000,
        )
    except Exception as exc:
        log(f"[RECONCILE CLOSE] {pos.symbol} | failed trade history lookup | {exc}")
        return None
    stop_trigger_ms = stop_trigger_time_for_position(
        client,
        pos,
        start_ms=start_ms,
        end_ms=end_ms,
    )
    close_side = close_side_for_position(pos.direction)
    candidates: list[dict[str, Any]] = []
    for row in trades:
        if not isinstance(row, dict):
            continue
        if str(row.get("side", "")).upper() != close_side:
            continue
        trade_ms = int(trade_float(row, "time", 0.0))
        if opened_ms is not None and trade_ms < opened_ms:
            continue
        if abs(trade_net_realized_pnl_usdt(row)) <= 1e-12 and abs(trade_float(row, "qty", 0.0)) <= 1e-12:
            continue
        candidates.append(row)
    if not candidates:
        return None

    target_qty = max(0.0, float(pos.qty_open))
    selected: list[dict[str, Any]] = []
    total_qty = 0.0
    for row in sorted(candidates, key=lambda r: int(trade_float(r, "time", 0.0)), reverse=True):
        selected.append(row)
        total_qty += abs(trade_float(row, "qty", 0.0))
        if target_qty <= 0.0 or total_qty >= max(0.0, target_qty - 1e-8):
            break
    if not selected:
        return None
    qty = sum(abs(trade_float(row, "qty", 0.0)) for row in selected)
    notional = sum(abs(trade_float(row, "qty", 0.0)) * trade_float(row, "price", 0.0) for row in selected)
    pnl = sum(trade_net_realized_pnl_usdt(row) for row in selected)
    close_ms = max(int(trade_float(row, "time", 0.0)) for row in selected)
    avg_price = notional / qty if qty > 0.0 else float(pos.current_stop_loss or pos.stop_loss or pos.entry)
    is_stop = False
    if stop_trigger_ms is not None:
        is_stop = abs(int(stop_trigger_ms) - int(close_ms)) <= 5_000
    return {
        "price": float(avg_price),
        "qty": float(qty),
        "pnl": float(pnl),
        "time_iso": iso_from_ms(close_ms),
        "is_stop": bool(is_stop),
        "trigger_price": float(pos.current_stop_loss or pos.stop_loss or pos.entry),
    }
