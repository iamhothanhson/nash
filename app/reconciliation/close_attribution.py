"""Finalize a position close when the exchange is flat (reconcile or manual)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pandas as pd

from analysis.collect_position_analysis_data import _OHLCV_CACHE, collect_regime_for_trade
from app.backtesting.backtest import _fetch_klines
from coins.loader import price_rounding_decimal
from core.rounding import format_price, round_usd
from app.config import settings
from execution.execution_engine import ExecutionEngine
from monitoring import risk_limit_tracking
from monitoring.events import emit_mode_event, strip_event_and_symbol_prefix
from monitoring.logger import log
from monitoring.messages import format_close_console_line
from monitoring.position_journal import duration_minutes, log_position_closed
from position_management.staged import ManagedPosition
from reconciliation.exchange_trades import (
    exchange_journal_balance_usdt,
    exchange_journal_close_metrics,
    resolve_flat_close_fill,
)
from trading.symbol_close_tracking import closed_5m_bar_ts_from_iso, record_symbol_close_bar

if TYPE_CHECKING:
    pass

_LOSS_SCAN_DAYS_1H = 7
_LOSS_SCAN_DAYS_15M = 3
_LOSS_SCAN_DAYS_5M = 3


def _position_side_label(pos: ManagedPosition) -> str:
    return "LONG" if str(pos.direction).upper() == "LONG" else "SHORT"


def _open_position_count(positions: list[ManagedPosition] | None) -> int:
    if not positions:
        return 0
    return sum(
        1
        for p in positions
        if not bool(getattr(p, "closed", False)) and float(getattr(p, "qty_open", 0.0)) > 1e-12
    )


def finalize_exchange_flat_close(
    engine: ExecutionEngine,
    pos: ManagedPosition,
    *,
    positions: list[ManagedPosition] | None = None,
) -> None:
    """
    Exchange has no position; local still open. Attribute close, journal, alert, mark closed.
    """
    if bool(pos.close_journal_logged):
        pos.qty_open = 0.0
        pos.closed = True
        return

    fill = resolve_flat_close_fill(engine, pos)
    qty = float(fill["qty"])
    exit_px = float(fill["price"])
    pnl = float(fill["pnl"])
    close_iso = str(fill["time_iso"])
    close_bar_ts = closed_5m_bar_ts_from_iso(close_iso)
    if close_bar_ts is not None:
        record_symbol_close_bar(pos.symbol, close_bar_ts)
    pos.realized_pnl += pnl
    pos.qty_open = 0.0
    pos.closed = True
    event = "SL HIT" if bool(fill["is_stop"]) else "EXCHANGE FLAT"

    pd = price_rounding_decimal(pos.symbol)
    trigger_px = float(fill.get("trigger_price", pos.current_stop_loss or pos.stop_loss or pos.entry))
    px_s = format_price(exit_px, pd)
    trigger_s = format_price(trigger_px, pd)
    tick = 10 ** (-pd) if pd > 0 else 0.01
    if event == "SL HIT" and abs(float(exit_px) - trigger_px) > tick * 0.5:
        price_label = f"Trigger: {trigger_s} | Fill: {px_s}"
    else:
        price_label = f"Price: {px_s}"
    size_closed_usdt = round_usd(float(pos.entry) * qty, 2)
    pnl_v = round_usd(pnl, 2)
    emit_mode_event(
        settings.MODE,
        pos.symbol,
        _position_side_label(pos),
        event,
        (
            f"{price_label} | Closed: {size_closed_usdt:.2f} USDT | "
            f"Remaining: 0.00 USDT | PNL: {pnl_v:+.2f} USDT"
        ),
    )

    balance = exchange_journal_balance_usdt(engine)
    if balance is None:
        balance = float(settings.INITIAL_CAPITAL)
    ex_exchange_pnl: float | None = None
    if settings.MODE in ("live", "demo"):
        ex_snap = exchange_journal_close_metrics(engine, pos)
        if ex_snap is not None:
            ex_exchange_pnl = float(ex_snap["realized_pnl_usdt"])
        else:
            ex_exchange_pnl = float(fill["pnl"])
    open_after_close = _open_position_count(positions)
    risk_limit_tracking.record_full_position_close(
        exchange_pnl_usdt=ex_exchange_pnl,
        internal_realized_pnl_usdt=float(pos.realized_pnl),
        journal_balance_usdt=float(balance),
        max_losses_per_day=int(settings.MAX_LOSSES_PER_DAY),
        open_positions=open_after_close,
    )
    log_position_closed(
        time_iso=close_iso,
        symbol=pos.symbol,
        direction=pos.direction,
        open_time_iso=str(pos.open_time_iso or ""),
        entry=float(pos.entry),
        stop_loss=float(pos.stop_loss),
        tp1=float(pos.tp1),
        tp2=float(pos.tp2),
        tp3=float(pos.tp3),
        qty_total=float(pos.qty_total),
        leverage=int(settings.LEVERAGE),
        risk_usdt=float(pos.initial_risk_usd),
        pnl_usdt=float(pos.realized_pnl),
        balance_usdt=float(balance),
        exchange_pnl_usdt=ex_exchange_pnl,
        tp1_hit=bool(getattr(pos, "hit_tp1", False)),
        tp2_hit=bool(getattr(pos, "hit_tp2", False)),
        tp3_hit=bool(getattr(pos, "hit_tp3", False)),
        closed_reason=str(event),
        strategy_family=str(getattr(pos, "strategy_family", "liquidity")),
        setup_type=str(getattr(pos, "setup_type", "unknown")),
    )
    close_line = format_close_console_line(
        symbol=pos.symbol,
        size_usdt=float(pos.entry) * float(pos.qty_total),
        leverage=int(settings.LEVERAGE),
        entry=float(pos.entry),
        exit_px=exit_px,
        duration_minutes_val=duration_minutes(pos.open_time_iso, close_iso),
        final_pnl=float(pos.realized_pnl),
        exchange_pnl_usdt=ex_exchange_pnl,
        price_decimals=pd,
    )
    log(
        f"[CLOSE] {pos.symbol} | {strip_event_and_symbol_prefix(close_line, 'CLOSE', pos.symbol)}",
        strip_setup=True,
    )
    emit_mode_event(
        settings.MODE,
        pos.symbol,
        _position_side_label(pos),
        "CLOSE",
        strip_event_and_symbol_prefix(close_line, "CLOSE", pos.symbol),
    )
    risk_limit_tracking.notify_performance_snapshot_after_close(open_positions=open_after_close)
    pos.close_journal_logged = True
    if settings.MODE in ("live", "demo"):
        try:
            engine.cancel_orders_for_flat_position(pos, reason=str(event))
        except Exception as exc:
            log(f"[ORDER CLEANUP] {pos.symbol} | reconcile flat close | {exc}")

    loss_pnl = ex_exchange_pnl if ex_exchange_pnl is not None else pnl
    if settings.ANALYZE_LOSSES:
        try:
            pos_sym = str(pos.symbol).strip().upper()
            cached = _OHLCV_CACHE.get(pos_sym, {})
            df_loss_1h = cached.get("1h") or _fetch_klines(pos_sym, "1h", _LOSS_SCAN_DAYS_1H)
            df_loss_15m = cached.get("15m") or _fetch_klines(pos_sym, "15m", _LOSS_SCAN_DAYS_15M)
            df_loss_5m = cached.get("5m") or _fetch_klines(pos_sym, "5m", _LOSS_SCAN_DAYS_5M)
            opened_dt = datetime.fromisoformat(pos.open_time_iso.replace("Z", "+00:00"))
            closed_dt = datetime.fromisoformat(close_iso.replace("Z", "+00:00"))
            dur = duration_minutes(pos.open_time_iso, close_iso)
            collect_regime_for_trade(
                df_loss_1h,
                df_loss_15m if not df_loss_15m.empty else pd.DataFrame(),
                df_loss_5m,
                pos_sym,
                opened_dt,
                closed_dt,
                {
                    "side": pos.direction,
                    "entry": pos.entry,
                    "stop_loss": pos.stop_loss,
                    "pnl": loss_pnl,
                    "strategy_setup": getattr(pos, "setup_type", "unknown"),
                    "bars_held": max(1, round(dur / 5.0)),
                    "tp_hit": bool(getattr(pos, "hit_tp1", False) or getattr(pos, "hit_tp2", False) or getattr(pos, "hit_tp3", False)),
                    "tp1_hit": bool(getattr(pos, "hit_tp1", False)),
                    "tp2_hit": bool(getattr(pos, "hit_tp2", False)),
                    "tp3_hit": bool(getattr(pos, "hit_tp3", False)),
                    "closed_reason": str(event),
                    "market_structure": getattr(pos, "market_structure", "Range"),
                    "market_regime_detail": getattr(pos, "market_regime_detail", None),
                },
            )
        except Exception as exc:
            log(f"[LOSS TRACE] {pos.symbol} | reconcile flat close | collect_regime_for_trade failed: {exc}")
