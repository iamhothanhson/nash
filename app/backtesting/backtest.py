from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import time
from collections import Counter, defaultdict
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

import sys

# Add project root to sys.path to allow importing from config, execution, and strategy
project_root = str(Path(__file__).resolve().parent.parent)
if project_root not in sys.path:
    sys.path.append(project_root)

from coins.loader import (
    get_coin_config,
    passes_coin_execution_gates,
    price_rounding_decimal,
    resolve_bars_since_last_close_min,
    symbol_at_per_symbol_cap,
    symbol_entry_blocked,
)
from common.rounding import format_price, round_price, round_qty, round_ratio, round_usd
from config import settings
from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK, LIQUIDITY_SWEEP, LIQUIDITY_SWEEP_REVERSAL, TREND, TREND_FOLLOWING
from analysis.collect_position_analysis_data import collect_regime_for_trade
from config.backtest_config import LOSS_FILTER
from loss_filter.loss_filter import breakout_filter, sweep_filter
from intelligence.ai_filter import ai_gate_score_tier, ai_gate_trade_metrics
from intelligence.ai_router import evaluate_trade as evaluate_ai_trade
from marketplace.fetcher import fetch_market_data_range, prefetch_history_symbols, _uses_history_ohlcv
from monitoring.logger import (
    flush_backtest_log_buffer,
    log,
    reset_backtest_logs_for_new_run,
    set_backtest_file_logging,
)
from monitoring.messages import (
    format_close_console_line,
    format_exit_decision_close_line,
    format_position_open_standard_line,
    format_risk_flow_line,
)
from monitoring.position_journal import (
    duration_minutes,
    infer_journal_closed_reason,
    log_position_closed,
    log_position_open,
)
from monitoring import risk_limit_tracking
from portfolio.capital_tracker import (
    VirtualAccount,
    portfolio_available_balance,
    positions_open_notional,
)
from trading.signal_engine import get_signal
from trading.symbol_close_tracking import (
    count_bars_since_close_5m,
    get_last_close_bar_ts,
    log_entry_after_bars_skip,
    record_symbol_close_bar,
    reset_symbol_close_tracking,
)
from position_management.exit_bar_utils import (
    build_exit_bar_slice,
    decide_exit_from_bar_slice,
    log_exit_input_parity,
)
from position_management.exit_manager import (
    ExitManagerConfig,
    decide_exit,
    is_immediate_forced_exit_reason,
)
from position_management import hard_stop
from position_management.exit_tuning import build_exit_manager_config
from position_management.roi import leveraged_roi_percent
from position_management.staged import (
    ManagedPosition,
    apply_staged_management,
    atr_from_df5,
    log_tp1_breakeven_memory,
)
from order_planning.order_planner import DailyState, build_order_plan, risk_controls_allow
from risk.risk_multiplier_manager import compute_regime_risk_multiplier, is_skip_reason_insufficient_data
from strategy.liquidity_sweep_reversal.sweep_revesal_config import liquidity_scan_5m_bars
from portfolio.portfolio_allocator import (
    compute_strength,
    compute_weights,
)

FEE_RATE = 0.0004

_SECONDS_PER_DAY = 86400.0

Position = ManagedPosition


def compute_trade_metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Aggregate TP progression and exit labels from per-trade dicts:
    tp1_hit, tp2_hit, tp3_hit, sl_hit, time_exit, exit_reason (str).
    """
    tp1_total = sum(1 for t in trades if t.get("tp1_hit"))
    if tp1_total == 0:
        return {}

    def _ratio(num: int, den: int) -> dict[str, float | int]:
        den_f = float(den)
        raw_r = (float(num) / den_f) if den_f > 0 else 0.0
        return {"count": int(num), "ratio": round_ratio(raw_r, 2)}

    tp1_to_exit = sum(1 for t in trades if t.get("tp1_hit") and t.get("time_exit"))
    tp1_to_tp2 = sum(1 for t in trades if t.get("tp1_hit") and t.get("tp2_hit"))
    tp1_to_tp3 = sum(1 for t in trades if t.get("tp1_hit") and t.get("tp3_hit"))
    tp1_to_sl = sum(1 for t in trades if t.get("tp1_hit") and t.get("sl_hit"))

    mfe_exit = sum(1 for t in trades if str(t.get("exit_reason", "")).strip() == "mfe_drawdown_exceeded")
    sl_exit = sum(1 for t in trades if t.get("sl_hit"))

    return {
        "tp1_total": int(tp1_total),
        "tp1_to_exit": _ratio(tp1_to_exit, tp1_total),
        "tp1_to_tp2": _ratio(tp1_to_tp2, tp1_total),
        "tp1_to_tp3": _ratio(tp1_to_tp3, tp1_total),
        "tp1_to_sl": _ratio(tp1_to_sl, tp1_total),
        "exit_breakdown": {
            "mfe_exit": int(mfe_exit),
            "sl_exit": int(sl_exit),
        },
    }


def _filter_trade_records_by_window(
    records: list[dict[str, Any]],
    *,
    end_ts: float,
    start_ts: float,
    window_days: int,
) -> list[dict[str, Any]]:
    """Trades closed on or after max(simulation start, end - window_days)."""
    if end_ts <= 0:
        return []
    cutoff = end_ts - float(window_days) * _SECONDS_PER_DAY
    lo = max(float(start_ts), float(cutoff))
    return [r for r in records if float(r.get("close_ts", 0.0)) >= lo]


def _trade_metrics_for_standard_windows(
    records: list[dict[str, Any]],
    *,
    end_ts: float,
    start_ts: float,
    sim_days: int,
) -> dict[str, dict[str, Any]]:
    """Metrics for 30 / 60 / 90 calendar-day lookbacks (requires sim at least that long).

    Also emits ``str(sim_days)`` for TP-path stats over the actual simulated window.
    """
    out: dict[str, dict[str, Any]] = {}
    for w in (30, 60, 90):
        if int(sim_days) < int(w):
            out[str(w)] = {}
            continue
        sub = _filter_trade_records_by_window(records, end_ts=end_ts, start_ts=start_ts, window_days=int(w))
        out[str(w)] = compute_trade_metrics(sub)
    sk = str(int(sim_days))
    sub_run = _filter_trade_records_by_window(
        records, end_ts=end_ts, start_ts=start_ts, window_days=int(sim_days)
    )
    out[sk] = compute_trade_metrics(sub_run)
    return out


def _zip_trade_path_pairs(result: dict[str, Any]) -> list[tuple[float, dict[str, Any]]]:
    """Align realized PnL list with ``trade_path_records`` (same append order in the sim)."""
    records = result.get("trade_path_records") if isinstance(result.get("trade_path_records"), list) else []
    trades = result.get("trades") if isinstance(result.get("trades"), list) else []
    if not records:
        return []
    if len(trades) >= len(records):
        return [
            (float(trades[i]), records[i])
            for i in range(len(records))
            if isinstance(records[i], dict)
        ]
    # Fallback: records without aligned ``trades`` list (legacy / partial result).
    return [
        (float(rec.get("realized_pnl", 0.0)), rec)
        for rec in records
        if isinstance(rec, dict)
    ]


def _pairs_in_close_window(
    pairs: list[tuple[float, dict[str, Any]]],
    *,
    end_ts: float,
    start_ts: float,
    window_days: int,
) -> list[tuple[float, dict[str, Any]]]:
    """Same calendar window as ``_filter_trade_records_by_window`` (closed trades on/after cutoff)."""
    if end_ts <= 0:
        return []
    cutoff = end_ts - float(window_days) * _SECONDS_PER_DAY
    lo = max(float(start_ts), float(cutoff))
    return [(pnl, rec) for pnl, rec in pairs if float(rec.get("close_ts", 0.0)) >= lo]


def _aggregate_exit_metrics_for_pairs(pairs: list[tuple[float, dict[str, Any]]]) -> dict[str, Any]:
    """
    Build ``time_exit`` / ``stop_loss`` / ``target_profit`` blocks for one lookback window.

    Time-exit sub-keys match ``decide_exit`` reasons; generic ``TIME EXIT`` string is rolled into
    ``unspecified`` when present.

    ``entry_time_exit``: time exits before any TP (no ``tp1_hit`` / ``tp2_hit``), with win/loss.
    ``tp*_time_exit``: other time exits by deepest TP before exit (``tp2_hit`` else ``tp1_hit``).

    ``stop_loss.SL``: stopped at initial SL only (``sl_hit`` and no ``tp1_hit`` — excludes
    breakeven / post-TP1 stops). Complements ``target_profit`` so
    ``SL + Stop_At_TP1 + Stop_At_TP2 + Stop_At_TP3`` equals total closed trades.

    ``target_profit``: deepest TP milestone reached, keyed as ``Stop_At_TP1`` / ``Stop_At_TP2`` /
    ``Stop_At_TP3`` (trade hit TP1 only, TP2 but not TP3, or TP3). Win/loss on total trade PnL.
    """
    time_reasons = (
        "mfe_drawdown_exceeded",
    )

    def wl_bucket() -> dict[str, int]:
        return {"total_count": 0, "win": 0, "loss": 0}

    def bump_wl(b: dict[str, int], pnl: float) -> None:
        b["total_count"] += 1
        if pnl > 0:
            b["win"] += 1
        elif pnl < 0:
            b["loss"] += 1

    te_sub = {k: wl_bucket() for k in time_reasons}
    te_unspec = wl_bucket()
    te_total = wl_bucket()
    entry_time_exit = wl_bucket()
    tp1_time_exit = {"total_count": 0}
    tp2_time_exit = {"total_count": 0}

    sl_sub = {"SL": wl_bucket()}

    tp_prof = {k: wl_bucket() for k in ("Stop_At_TP1", "Stop_At_TP2", "Stop_At_TP3")}

    for pnl, rec in pairs:
        er = str(rec.get("exit_reason", "")).strip()
        er_l = er.lower()
        te_flag = bool(rec.get("time_exit"))
        is_time = te_flag or er in time_reasons or er_l == "time exit"
        if is_time:
            bump_wl(te_total, pnl)
            if er in time_reasons:
                bump_wl(te_sub[er], pnl)
            else:
                bump_wl(te_unspec, pnl)
            tp1h = bool(rec.get("tp1_hit"))
            tp2h = bool(rec.get("tp2_hit"))
            if tp2h:
                tp2_time_exit["total_count"] += 1
            elif tp1h:
                tp1_time_exit["total_count"] += 1
            else:
                bump_wl(entry_time_exit, pnl)

        if bool(rec.get("sl_hit")) and not bool(rec.get("tp1_hit")):
            bump_wl(sl_sub["SL"], pnl)

        tp1h = bool(rec.get("tp1_hit"))
        tp2h = bool(rec.get("tp2_hit"))
        tp3h = bool(rec.get("tp3_hit"))
        if tp3h or er == "TP3":
            bump_wl(tp_prof["Stop_At_TP3"], pnl)
        elif tp2h:
            bump_wl(tp_prof["Stop_At_TP2"], pnl)
        elif tp1h:
            bump_wl(tp_prof["Stop_At_TP1"], pnl)

    time_exit_block: dict[str, Any] = {
        "total_count": int(te_total["total_count"]),
        "mfe_drawdown_exceeded": dict(te_sub["mfe_drawdown_exceeded"]),
        "entry_time_exit": dict(entry_time_exit),
        "tp1_time_exit": dict(tp1_time_exit),
        "tp2_time_exit": dict(tp2_time_exit),
    }
    if int(te_unspec["total_count"]) > 0:
        time_exit_block["unspecified"] = dict(te_unspec)

    return {
        "total_trades": len(pairs),
        "time_exit": time_exit_block,
        "stop_loss": {"SL": dict(sl_sub["SL"])},
        "target_profit": dict(tp_prof),
    }


def _build_exit_metrics_artifact_payload(result: dict[str, Any], *, sim_days: int) -> dict[str, Any]:
    """Exit breakdown for this run only (single key ``str(sim_days)``, e.g. ``7``, ``30``, ``60``)."""
    pairs = _zip_trade_path_pairs(result)
    end_ts = float(result.get("simulation_end_ts", 0.0) or 0.0)
    start_ts = float(result.get("simulation_start_ts", 0.0) or 0.0)
    sim_d = int(sim_days)
    run_pairs = _pairs_in_close_window(pairs, end_ts=end_ts, start_ts=start_ts, window_days=sim_d)
    return {str(sim_d): _aggregate_exit_metrics_for_pairs(run_pairs)}


def _write_backtest_exit_metrics_artifact(result: dict[str, Any], *, sim_days: int) -> None:
    root = Path(__file__).resolve().parent.parent.parent / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "backtest_exit_metrics.json"
    payload = _build_exit_metrics_artifact_payload(result, sim_days=int(sim_days))
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_backtest_exit_baseline_artifact(result: dict[str, Any], *, sim_days: int) -> None:
    root = Path(__file__).resolve().parent.parent.parent / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    target = root / "backtest_exit_baseline.json"
    payload = _build_exit_metrics_artifact_payload(result, sim_days=int(sim_days))
    target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


@dataclass
class _EntrySnapshot:
    """Frozen entry from a baseline (no-AI) run for AI-filtered replay."""

    ts: Any
    sym: str
    plan: dict[str, Any]
    strategy_family: str
    rsi: Any
    volatility: Any


def _filter_snapshots_with_ai(
    snapshots: list[_EntrySnapshot],
) -> tuple[list[_EntrySnapshot], int, int, int]:
    take = skip = skip_a = 0
    filtered: list[_EntrySnapshot] = []
    for snap in snapshots:
        plan = snap.plan
        sig_map = {
            "setup_grade": plan.get("setup_grade"),
            "setup_score": plan.get("setup_score"),
        }
        if not ai_gate_score_tier(sig_map, plan):
            filtered.append(snap)
            continue
        entry = float(plan.get("entry", 0.0))
        sl = float(plan.get("stop_loss", 0.0))
        tp1 = float(plan.get("tp1", 0.0))
        risk = abs(entry - sl)
        reward = abs(tp1 - entry)
        r_multiple = (reward / risk) if risk > 0 else 0.0
        direction = str(plan.get("direction", "")).upper()
        trade_data = {
            "symbol": snap.sym,
            "direction": direction,
            "setup_grade": str(plan.get("setup_grade", "") or ""),
            "confirmation_mode": str(plan.get("confirmation_mode", "") or ""),
            "entry": entry,
            "stop_loss": sl,
            "tp1": tp1,
            "price": entry,
            "rsi": snap.rsi,
            "volatility": snap.volatility,
            "trend": direction,
            "action": "BUY" if direction == "LONG" else "SELL",
            "setup_score": plan.get("setup_score", 0),
            "confidence": float(plan.get("setup_score", 0) or 0) / 12.0,
            "r_multiple": r_multiple,
            "min_confidence": float(settings.AI_MIN_CONFIDENCE),
        }
        if not ai_gate_trade_metrics(trade_data):
            filtered.append(snap)
            continue
        ai_result = evaluate_ai_trade(trade_data)
        decision = str(ai_result.get("decision", "SKIP")).upper()
        if decision == "SKIP":
            skip += 1
            if str(plan.get("setup_grade", "")).strip().upper() == "A":
                skip_a += 1
            continue
        take += 1
        filtered.append(snap)
    return filtered, take, skip, skip_a


def _fetch_klines(symbol: str, interval: str, days: int) -> pd.DataFrame:
    frame = fetch_market_data_range(symbol=symbol, timeframe=interval, days=days)
    # History-only backtests can operate on stale local datasets; anchor the requested
    # window to the latest local candle instead of wall-clock "now".
    if (
        bool(getattr(settings, "BACKTEST_HISTORY_ANCHOR_LATEST", True))
        and _uses_history_ohlcv()
    ):
        full = frame
        if full.empty:
            # Pull all cached history (no network when HISTORY_AUTO_FETCH=false), then slice.
            full = fetch_market_data_range(symbol=symbol, timeframe=interval, days=3650)
        if not full.empty and "time" in full.columns:
            end_ms = int(pd.to_numeric(full["time"], errors="coerce").max())
            min_ms = end_ms - int(days) * 86_400_000
            frame = full[full["time"] >= min_ms].reset_index(drop=True)
    if frame.empty:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(frame["time"], unit="ms", utc=True),
            "open": frame["open"].astype(float),
            "high": frame["high"].astype(float),
            "low": frame["low"].astype(float),
            "close": frame["close"].astype(float),
            "volume": frame["volume"].astype(float),
        }
    ).sort_values("timestamp").drop_duplicates(subset=["timestamp"]).reset_index(drop=True)


def _materialize_backtest_timestamp_columns(
    data: dict[str, dict[str, pd.DataFrame]],
) -> None:
    """
    Index-only OHLC frames force exit_bar_utils.ensure_timestamp_column to copy the
    full dataframe on every bar; add timestamp once at load time.
    """
    for frames in data.values():
        for interval in ("1m", "5m", "15m", "1h"):
            df = frames.get(interval)
            if df is None or df.empty or "timestamp" in df.columns:
                continue
            aug = df.copy()
            aug["timestamp"] = pd.to_datetime(aug.index, utc=True)
            frames[interval] = aug


def _entry_slice_reset_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Match legacy `.reset_index()` after as-of slice. Materialized OHLC frames carry both a
    DatetimeIndex and a `timestamp` column; resetting would duplicate the column — drop index only.
    """
    if "timestamp" in df.columns:
        return df.reset_index(drop=True)
    return df.reset_index()


def _sorted_dtindex_contains(idx: pd.DatetimeIndex, ts_utc: pd.Timestamp) -> bool:
    """O(log n) membership on a sorted unique DatetimeIndex (avoids hashing the whole index)."""
    if idx.empty or len(idx) == 0:
        return False
    pos = int(idx.searchsorted(ts_utc, side="left"))
    return pos < len(idx) and idx[pos] == ts_utc


def _normalize_timeline_ts(ts: Any) -> pd.Timestamp:
    ts_pd = pd.Timestamp(ts)
    if ts_pd.tzinfo is None:
        return ts_pd.tz_localize("UTC")
    return ts_pd.tz_convert("UTC")


def _precompute_indicator_columns(data: dict[str, dict[str, pd.DataFrame]]) -> None:
    """Add pre-computed columns for EMA and RSI (EWMA converges quickly on
    strategy-level 200+ row slices); ATR and ADX are excluded because their
    column cache check changes results for position-management tail windows."""
    from indicators import calculate_ema, calculate_rsi

    for sym, frames in data.items():
        for interval, df in frames.items():
            if df is None or df.empty:
                continue
            if interval in ("5m", "15m"):
                if "ema_20" not in df.columns:
                    df["ema_20"] = calculate_ema(df, 20)
                if "rsi_14" not in df.columns:
                    df["rsi_14"] = calculate_rsi(df, 14)
            if interval in ("15m",):
                if "ema_50" not in df.columns:
                    df["ema_50"] = calculate_ema(df, 50)
            if interval == "1h":
                for p in (20, 50, 200):
                    col = f"ema_{p}"
                    if col not in df.columns:
                        df[col] = calculate_ema(df, p)
                if "rsi_14" not in df.columns:
                    df["rsi_14"] = calculate_rsi(df, 14)


def _slice_asof_tail_reset_index(
    df: pd.DataFrame,
    ts: Any,
    max_rows: int,
    *,
    ts_utc: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Same rows as df[df.index <= ts].tail(max_rows).reset_index() without scanning
    the full index with a boolean mask (hot path for entry evaluation).
    """
    if df.empty or max_rows <= 0:
        return _entry_slice_reset_index(df.iloc[:0])
    idx = df.index
    if ts_utc is not None:
        ts_pd = ts_utc
    else:
        ts_pd = _normalize_timeline_ts(ts)
    if not idx.is_monotonic_increasing:
        return _entry_slice_reset_index(df[df.index < ts_pd].tail(max_rows))
    pos = int(idx.searchsorted(ts_pd, side="left")) - 1
    if pos < 0:
        return _entry_slice_reset_index(df.iloc[:0])
    start = max(0, pos - max_rows + 1)
    return _entry_slice_reset_index(df.iloc[start : pos + 1])


def _latest_closed_5m_candle_ts(df5: pd.DataFrame) -> float | None:
    """Most recent closed 5m bar (penultimate row avoids partially formed last bar)."""
    try:
        if len(df5) < 2:
            return None
        if "timestamp" in df5.columns:
            ts = pd.Timestamp(df5["timestamp"].iloc[-2])
        else:
            ts = pd.Timestamp(df5.index[-2])
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        else:
            ts = ts.tz_convert("UTC")
        return float(ts.timestamp())
    except Exception:
        return None


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    gross = (exit_px - entry) * qty if direction == "LONG" else (entry - exit_px) * qty
    fee = (entry * qty + exit_px * qty) * FEE_RATE
    return gross - fee


def _apply_exit_slippage(price: float, direction: str, slippage_bps: float) -> float:
    """Apply adverse slippage to exit price (sell lower for longs, buy higher for shorts)."""
    bps = max(0.0, float(slippage_bps))
    mult = bps / 10_000.0
    if str(direction).strip().upper() == "LONG":
        return float(price) * (1.0 - mult)
    return float(price) * (1.0 + mult)


def _execute_forced_close_step(
    *,
    pos: Position,
    mark_px: float,
    reason_tag: str,
    partial_fill_ratio: float,
    slippage_bps: float,
) -> list[dict[str, float | str]]:
    """
    Execute one forced-close step (time/hard-stop), with optional partial fill and slippage.
    Returns non-empty fills list for this step. Adds CLOSE fill only when fully closed.
    """
    qty_open = max(0.0, float(pos.qty_open))
    if qty_open <= 0.0:
        return []
    ratio = min(1.0, max(0.05, float(partial_fill_ratio)))
    qty_exec = min(qty_open, qty_open * ratio)
    exit_px = _apply_exit_slippage(float(mark_px), str(pos.direction), float(slippage_bps))
    pnl_exec = float(_pnl(str(pos.direction), float(pos.entry), float(exit_px), float(qty_exec)))
    pos.realized_pnl += pnl_exec
    pos.qty_open = max(0.0, qty_open - qty_exec)
    fills: list[dict[str, float | str]] = [
        {
            "tag": str(reason_tag),
            "price": float(exit_px),
            "qty_closed": float(qty_exec),
            "qty_remaining": float(pos.qty_open),
            "pnl": float(pnl_exec),
        }
    ]
    if pos.qty_open <= 1e-12:
        pos.qty_open = 0.0
        pos.closed = True
        fills.append(
            {
                "tag": "CLOSE",
                "price": float(exit_px),
                "qty_closed": float(qty_exec),
                "qty_remaining": 0.0,
                "pnl": float(pos.realized_pnl),
            }
        )
    return fills


def _position_roi_percent(pos: Position, mark_price: float) -> float:
    return leveraged_roi_percent(
        entry=float(pos.entry),
        direction=str(pos.direction),
        mark_price=float(mark_price),
        leverage=float(settings.LEVERAGE),
    )


def _max_drawdown(equity: list[float]) -> float:
    if not equity:
        return 0.0
    peak = equity[0]
    worst = 0.0
    for x in equity:
        peak = max(peak, x)
        if peak > 0:
            worst = max(worst, (peak - x) / peak)
    return worst


# Display order for text report (matches common read order: momentum / primary / secondary / …).
_SETUP_REPORT_ORDER = (LIQUIDITY_SWEEP_REVERSAL, BREAKOUT, BREAKOUT_RETEST, PULLBACK)
_SETUP_LABELS: dict[str, str] = {
    LIQUIDITY_SWEEP_REVERSAL: "Liquidity Sweep",
    BREAKOUT: "Breakout",
    BREAKOUT_RETEST: "Breakout Retest",
    PULLBACK: "Pullback",
}
_GRADE_REPORT_ORDER = ("A+", "A")
# Human-readable report labels (internal grade_counts keys stay "A+", etc.).
_GRADE_DISPLAY_LABELS: dict[str, str] = {
    "A+": "A+ Trades",
    "A": "A Trades",
}


def _setup_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    key, _ = item
    try:
        return (_SETUP_REPORT_ORDER.index(key), key)
    except ValueError:
        return (len(_SETUP_REPORT_ORDER), key)


def _grade_sort_key(item: tuple[str, int]) -> tuple[int, str]:
    key, _ = item
    try:
        return (_GRADE_REPORT_ORDER.index(key), key)
    except ValueError:
        return (len(_GRADE_REPORT_ORDER), key)


def format_backtest_report(result: dict[str, Any]) -> str:
    """Human-readable summary (stdout); numeric fields use fixed decimals like the sample report."""
    pf = result.get("profit_factor")
    if pf is None:
        pf_str = "n/a"
    else:
        pf_str = f"{float(pf):.2f}"

    roi = float(result.get("roi", 0.0))
    win_rate_pct = float(result.get("win_rate", 0.0)) * 100.0
    max_dd_pct = float(result.get("max_drawdown", 0.0)) * 100.0
    net_profit = float(result.get("net_profit", float(result["final_balance"]) - float(result["initial_balance"])))

    lines: list[str] = []
    portfolio = result.get("portfolio_symbols")
    if portfolio:
        lines.append(f"Portfolio: {portfolio}")
    lines.extend([
        f"Symbol: {result['symbol']}",
        f"Initial Balance: {float(result['initial_balance']):.2f}",
        f"Net Profit: {net_profit:+.2f}",
        f"ROI: {roi:+.2f}%",
        f"Total Trades: {result['total_trades']}",
        f"Trades per Day: {float(result['trades_per_day']):.2f}",
        f"Win Rate: {win_rate_pct:.2f}%",
        f"Profit Factor: {pf_str}",
        f"Max Drawdown: {max_dd_pct:.2f}%",
    ])
    setup_counts: dict[str, int] = result.get("setup_counts") or {}
    for key, n in sorted(setup_counts.items(), key=_setup_sort_key):
        label = _SETUP_LABELS.get(key, key.replace("_", " ").title())
        lines.append(f"{label}: {n}")

    grade_counts: dict[str, int] = result.get("grade_counts") or {}
    for key, n in sorted(grade_counts.items(), key=_grade_sort_key):
        label = _GRADE_DISPLAY_LABELS.get(key, key)
        lines.append(f"{label}: {n}")

    liquidity_attr = result.get("liquidity_attribution")
    trend_attr = result.get("trend_attribution")
    _liq_line = _liquidity_attribution_summary_line(liquidity_attr if isinstance(liquidity_attr, dict) else None)
    if _liq_line:
        lines.append(_liq_line)
    else:
        family_counts_fb: dict[str, int] = result.get("family_counts") or {}
        froi_fb: dict[str, float] = result.get("family_roi_percent") or {}
        lines.append(
            f"Sweep Reversal Trades: {int(family_counts_fb.get('liquidity', 0))}, "
            f"ROI: {float(froi_fb.get('liquidity', 0.0)):+.2f}%"
        )
    _tr_lines = _trend_attribution_summary_lines(trend_attr if isinstance(trend_attr, dict) else None)
    if _tr_lines:
        lines.extend(_tr_lines)
    else:
        family_counts_fb = result.get("family_counts") or {}
        froi_fb = result.get("family_roi_percent") or {}
        lines.append(
            f"Trend Following Trades: {int(family_counts_fb.get('trend', 0))}, "
            f"ROI: {float(froi_fb.get('trend', 0.0)):+.2f}%"
        )
    if "ai_take_total" in result or "ai_skip_total" in result:
        ai_take = int(result.get("ai_take_total", 0))
        ai_skip = int(result.get("ai_skip_total", 0))
        lines.append(f"AI SENT: {ai_take + ai_skip}")
        lines.append(f"AI TAKE: {ai_take}")
        lines.append(f"AI SKIP: {ai_skip}")

    return "\n".join(lines)


def format_summary_table(results: list[dict[str, Any]]) -> str:
    header = (
        f"{'Asset':<6} | {'Days':>4} | {'ROI':>8} | {'PF':>5} | "
        f"{'Win Rate':>8} | {'DD':>7} | {'Trades/day':>10}"
    )
    rows = [header]
    for result in results:
        pf = result.get("profit_factor")
        pf_str = "n/a" if pf is None else f"{float(pf):.2f}"
        asset = str(result.get("symbol", "")).upper().replace("USDT", "")
        rows.append(
            f"{asset:<6} | "
            f"{int(result.get('days', 0)):>4} | "
            f"{float(result.get('roi', 0.0)):+.2f}% | "
            f"{pf_str:>5} | "
            f"{float(result.get('win_rate', 0.0)) * 100.0:>7.2f}% | "
            f"{float(result.get('max_drawdown', 0.0)) * 100.0:>6.2f}% | "
            f"{float(result.get('trades_per_day', 0.0)):>10.2f}"
        )
    return "\n".join(rows)


def _per_symbol_report_lines(result: dict[str, Any]) -> list[str]:
    """Per-symbol KPI lines when --symbol filters report after a portfolio run."""
    per_symbol = result.get("per_symbol")
    if not isinstance(per_symbol, dict) or not per_symbol:
        return []
    lines: list[str] = []
    for sym in sorted(per_symbol.keys()):
        st = per_symbol[sym]
        if not isinstance(st, dict):
            continue
        pf = st.get("profit_factor")
        pf_str = "n/a" if pf is None else f"{float(pf):.2f}"
        short = sym.replace("USDT", "")
        lines.append(
            f"{short}: {int(st.get('trades', 0))} trades, "
            f"net={float(st.get('net_profit', 0.0)):+.2f} USDT, "
            f"margin ROI={float(st.get('roi', 0.0)):+.2f}%, "
            f"win={float(st.get('win_rate', 0.0)) * 100.0:.2f}%, pf={pf_str}"
        )
    return lines


def format_portfolio_summary(result: dict[str, Any]) -> str:
    pf = result.get("profit_factor")
    pf_str = "n/a" if pf is None else f"{float(pf):.2f}"
    coins = str(result.get("symbol", "")).replace(",", ", ").replace("USDT", "")
    report_filtered = bool(result.get("report_note"))
    grade_counts: dict[str, int] = result.get("grade_counts") or {}
    a_plus = int(grade_counts.get("A+", 0))
    a = int(grade_counts.get("A", 0))
    lines = [
        f"Coins: {coins}",
        f"Initial Balance: {float(result.get('initial_balance', 0.0)):.2f}",
        f"Net Profit: {float(result.get('net_profit', 0.0)):+.2f}",
        f"ROI: {float(result.get('roi', 0.0)):+.2f}%",
        f"Total Trades: {int(result.get('total_trades', 0))}",
        f"Trades per Day: {float(result.get('trades_per_day', 0.0)):.2f}",
        f"Win Rate: {float(result.get('win_rate', 0.0)) * 100.0:.2f}%",
        f"Profit Factor: {pf_str}",
        f"Max Drawdown: {float(result.get('max_drawdown', 0.0)) * 100.0:.2f}%",
    ]
    if not report_filtered:
        lines.extend([f"A+ Trades: {a_plus}", f"A Trades: {a}"])
        liquidity_attr_pf = result.get("liquidity_attribution")
        trend_attr_pf = result.get("trend_attribution")
        _liq_line_pf = _liquidity_attribution_summary_line(
            liquidity_attr_pf if isinstance(liquidity_attr_pf, dict) else None
        )
        if _liq_line_pf:
            lines.append(_liq_line_pf)
        else:
            fc_pf: dict[str, int] = result.get("family_counts") or {}
            froi_pf = result.get("family_roi_percent") or {}
            lines.append(
                f"Liquidity Reversal Trades: {int(fc_pf.get('liquidity', 0))}, "
                f"ROI: {float(froi_pf.get('liquidity', 0.0)):+.2f}%"
            )
        _tr_lines_pf = _trend_attribution_summary_lines(trend_attr_pf if isinstance(trend_attr_pf, dict) else None)
        if _tr_lines_pf:
            lines.extend(_tr_lines_pf)
        else:
            fc_pf = result.get("family_counts") or {}
            froi_pf = result.get("family_roi_percent") or {}
            lines.append(
                f"Trend Following Trades: {int(fc_pf.get('trend', 0))}, "
                f"ROI: {float(froi_pf.get('trend', 0.0)):+.2f}%"
            )
    else:
        lines.extend(_per_symbol_report_lines(result))
    if "ai_take_total" in result or "ai_skip_total" in result:
        ai_take = int(result.get("ai_take_total", 0))
        ai_skip = int(result.get("ai_skip_total", 0))
        lines.append(f"AI SENT: {ai_take + ai_skip}")
        lines.append(f"AI TAKE: {ai_take}")
        lines.append(f"AI SKIP: {ai_skip}")
    return "\n".join(lines)


def format_compare_table(rows: list[dict[str, Any]], total: dict[str, Any]) -> str:
    header = (
        f"{'Symbol':<9} | {'Trades':<6} | {'ROI (%)':>7} | "
        f"{'PNL (USDT)':>10} | {'Win Rate (%)':>12} | {'PF':>6} | {'Max DD (%)':>10} | "
        f"{'Peak Alloc (USDT)':>17} | "
        f"{'Avg Alloc (USDT)':>16} | {'Capital (USDT)':>14}"
    )
    sep = "-" * len(header)
    out = [header, sep]
    for row in rows:
        sym = str(row.get("symbol", "")).replace("USDT", "")
        trades = int(row.get("trades", 0))
        roi = float(row.get("roi", 0.0))
        win_rate = float(row.get("win_rate", 0.0))
        profit_factor = row.get("profit_factor")
        pf_str = "n/a" if profit_factor is None else f"{float(profit_factor):.2f}"
        max_drawdown = float(row.get("max_drawdown", 0.0))
        pnl = float(row.get("pnl", 0.0))
        capital = float(row.get("capital", 0.0))
        avg_alloc = float(row.get("avg_alloc", 0.0))
        out.append(
            f"{sym:<9} | {trades:<6d} | {roi:+7.2f} | "
            f"{pnl:+10.2f} | {win_rate:12.2f} | {pf_str:>6} | {max_drawdown:10.2f} | "
            f"{capital:+17.2f} | {avg_alloc:+16.2f} | {'':>14}"
        )
    out.append(sep)
    total_pf = total.get("profit_factor")
    total_pf_str = "n/a" if total_pf is None else f"{float(total_pf):.2f}"
    out.append(
        f"{'TOTAL':<9} | {int(total.get('trades', 0)):<6d} | "
        f"{float(total.get('roi', 0.0)):+7.2f} | "
        f"{float(total.get('pnl', 0.0)):+10.2f} | "
        f"{float(total.get('win_rate', 0.0)):12.2f} | "
        f"{total_pf_str:>6} | "
        f"{float(total.get('max_drawdown', 0.0)):10.2f} | "
        f"{float(total.get('capital', 0.0)):+17.2f} | "
        f"{float(total.get('avg_alloc', 0.0)):+16.2f} | "
        f"{float(total.get('initial_capital', 0.0)):+14.2f}"
    )
    return "\n".join(out)


def _normalize_strategy_family_key(strategy_family: str) -> str:
    """Map signal.strategy_family to backtest bucket liquidity | trend."""
    s = str(strategy_family).strip()
    if s in (TREND_FOLLOWING, TREND):
        return TREND
    return "liquidity"


def _empty_symbol_attribution() -> dict[str, Any]:
    return {
        "setup_counts": {},
        "grade_counts": {},
        "family_counts": {"liquidity": 0, TREND: 0},
        "family_setup_breakdown": {"liquidity": Counter(), TREND: Counter()},
        "family_margin_usdt": {"liquidity": 0.0, TREND: 0.0},
        "family_realized_pnl": {"liquidity": 0.0, TREND: 0.0},
        "trend_setup_realized_pnl": {PULLBACK: 0.0, BREAKOUT: 0.0, BREAKOUT_RETEST: 0.0},
        "trend_setup_margin_usdt": {PULLBACK: 0.0, BREAKOUT: 0.0, BREAKOUT_RETEST: 0.0},
    }


def _symbol_attribution_record_entry(
    bucket: dict[str, Any],
    *,
    setup_key: str,
    grade_key: str,
    family_key: str,
    margin_added: float,
) -> None:
    bucket["setup_counts"][setup_key] = int(bucket["setup_counts"].get(setup_key, 0)) + 1
    bucket["grade_counts"][grade_key] = int(bucket["grade_counts"].get(grade_key, 0)) + 1
    fc = bucket["family_counts"]
    fc[family_key] = int(fc.get(family_key, 0)) + 1
    fsb = bucket["family_setup_breakdown"]
    fsb.setdefault(family_key, Counter())[setup_key] += 1
    fm = bucket["family_margin_usdt"]
    fm[family_key] = float(fm.get(family_key, 0.0)) + float(margin_added)
    if family_key == TREND and setup_key in (PULLBACK, BREAKOUT, BREAKOUT_RETEST):
        tsm = bucket["trend_setup_margin_usdt"]
        tsm[setup_key] = float(tsm.get(setup_key, 0.0)) + float(margin_added)


def _symbol_attribution_record_close(
    bucket: dict[str, Any],
    *,
    family_attr: str,
    setup_type: str,
    trade_pnl: float,
) -> None:
    fam = family_attr if family_attr in ("liquidity", TREND) else _normalize_strategy_family_key(family_attr)
    frp = bucket["family_realized_pnl"]
    frp[fam] = float(frp.get(fam, 0.0)) + float(trade_pnl)
    if fam == TREND:
        setup_key = str(setup_type).strip().lower()
        tsp = bucket["trend_setup_realized_pnl"]
        if setup_key in tsp:
            tsp[setup_key] = float(tsp.get(setup_key, 0.0)) + float(trade_pnl)


def _serialize_per_symbol_attribution(
    per_symbol_attribution: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for sym, b in per_symbol_attribution.items():
        fsb = b.get("family_setup_breakdown") or {}
        out[sym] = {
            "setup_counts": dict(b.get("setup_counts") or {}),
            "grade_counts": dict(b.get("grade_counts") or {}),
            "family_counts": dict(b.get("family_counts") or {}),
            "family_setup_breakdown": {
                "liquidity": dict(fsb.get("liquidity", Counter())),
                TREND: dict(fsb.get(TREND, Counter())),
            },
            "family_margin_usdt": dict(b.get("family_margin_usdt") or {}),
            "family_realized_pnl": dict(b.get("family_realized_pnl") or {}),
            "trend_setup_realized_pnl": dict(b.get("trend_setup_realized_pnl") or {}),
            "trend_setup_margin_usdt": dict(b.get("trend_setup_margin_usdt") or {}),
        }
    return out


def _apply_symbol_attribution_slice(out: dict[str, Any], sym: str) -> dict[str, Any]:
    """Replace portfolio-wide setup/grade/family stats with one symbol's attribution."""
    psa = out.get("per_symbol_attribution")
    if not isinstance(psa, dict):
        return out
    attr = psa.get(sym)
    if not isinstance(attr, dict):
        return out
    ib = float(out.get("initial_balance", 0.0))
    setup_counts = dict(attr.get("setup_counts") or {})
    grade_counts = dict(attr.get("grade_counts") or {})
    family_counts = dict(attr.get("family_counts") or {"liquidity": 0, TREND: 0})
    frp = dict(attr.get("family_realized_pnl") or {"liquidity": 0.0, TREND: 0.0})
    fm = dict(attr.get("family_margin_usdt") or {"liquidity": 0.0, TREND: 0.0})
    fsb_raw = attr.get("family_setup_breakdown") or {}
    fsb = {
        "liquidity": Counter(fsb_raw.get("liquidity") or {}),
        TREND: Counter(fsb_raw.get(TREND) or {}),
    }
    tsp = attr.get("trend_setup_realized_pnl")
    tsm = attr.get("trend_setup_margin_usdt")
    out["setup_counts"] = setup_counts
    out["grade_counts"] = grade_counts
    out["family_counts"] = family_counts
    out["family_realized_pnl"] = frp
    out["family_margin_usdt"] = fm
    out["family_setup_breakdown"] = {
        "liquidity": dict(fsb["liquidity"]),
        TREND: dict(fsb[TREND]),
    }
    liq_n = int(family_counts.get("liquidity", 0))
    tr_n = int(family_counts.get(TREND, 0))
    liq_m = float(fm.get("liquidity", 0.0))
    tr_m = float(fm.get(TREND, 0.0))
    liq_net = float(frp.get("liquidity", 0.0))
    tr_net = float(frp.get(TREND, 0.0))
    out["family_avg_margin_usdt"] = {
        "liquidity": round((liq_m / liq_n) if liq_n > 0 else 0.0, 2),
        TREND: round((tr_m / tr_n) if tr_n > 0 else 0.0, 2),
    }
    out["family_roi_percent"] = {
        "liquidity": _strategy_roi_percent_on_avg_margin(liq_net, liq_m, liq_n, ib),
        TREND: _strategy_roi_percent_on_avg_margin(tr_net, tr_m, tr_n, ib),
    }
    liq_attr, tr_attr = _build_family_attribution_payload(
        family_counts=family_counts,
        family_realized_pnl=frp,
        family_margin_usdt=fm,
        family_setup_breakdown=fsb,
        initial_balance=ib,
        trend_setup_realized_pnl=tsp if isinstance(tsp, dict) else None,
        trend_setup_margin_usdt=tsm if isinstance(tsm, dict) else None,
    )
    out["liquidity_attribution"] = liq_attr
    out["trend_attribution"] = tr_attr
    pst = out.get("per_symbol_trades")
    if isinstance(pst, dict) and sym in pst:
        sym_trades = [float(x) for x in pst[sym]]
        wins = [x for x in sym_trades if x > 0]
        losses = [x for x in sym_trades if x < 0]
        gross_win = sum(wins)
        gross_loss = sum(losses)
        pf = (gross_win / abs(gross_loss)) if gross_loss < 0 else (float("inf") if gross_win > 0 else 0.0)
        out["profit_factor"] = None if pf == float("inf") else pf
    return out


def _strategy_roi_percent_on_avg_margin(
    net_usdt: float,
    total_margin_usdt: float,
    trades_count: int,
    initial_balance: float,
) -> float:
    """ROI % on average margin used per trade; falls back to vs initial balance."""
    n = max(0, int(trades_count))
    avg_margin = (float(total_margin_usdt) / float(n)) if n > 0 else 0.0
    if avg_margin > 1e-9:
        return round(float(net_usdt) / float(avg_margin) * 100.0, 2)
    ib = max(float(initial_balance), 1e-12)
    return round(float(net_usdt) / ib * 100.0, 2)


def _trend_setup_metrics_block(
    *,
    trades: int,
    net_usdt: float,
    margin_usdt: float,
    initial_balance: float,
) -> dict[str, Any]:
    """Per-setup trend metrics for JSON artifacts and console summary."""
    n = max(0, int(trades))
    m = float(margin_usdt)
    net = float(net_usdt)
    avg_m = (m / n) if n > 0 else 0.0
    return {
        "trades": n,
        "margin_usdt": round(m, 2),
        "avg_margin_usdt": round(avg_m, 2),
        "roi_percent": _strategy_roi_percent_on_avg_margin(net, m, n, initial_balance),
        "net_profit_usdt": round(net, 2),
    }


def _build_family_attribution_payload(
    *,
    family_counts: dict[str, int],
    family_realized_pnl: dict[str, float],
    family_margin_usdt: dict[str, float],
    family_setup_breakdown: dict[str, Counter[str]],
    initial_balance: float,
    trend_setup_realized_pnl: dict[str, float] | None = None,
    trend_setup_margin_usdt: dict[str, float] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Structured attribution for trend vs liquidity (reports + JSON artifacts)."""
    ib = max(float(initial_balance), 1e-12)
    liq_n = int(family_counts.get("liquidity", 0))
    tr_n = int(family_counts.get(TREND, 0))
    liq_bd = dict(family_setup_breakdown.get("liquidity", Counter()))
    tr_bd = dict(family_setup_breakdown.get(TREND, Counter()))
    liq_net = float(family_realized_pnl.get("liquidity", 0.0))
    tr_net = float(family_realized_pnl.get(TREND, 0.0))
    liq_m = float(family_margin_usdt.get("liquidity", 0.0))
    tr_m = float(family_margin_usdt.get(TREND, 0.0))
    sweep_n = int(liq_bd.get(LIQUIDITY_SWEEP_REVERSAL, 0))
    pb = int(tr_bd.get(PULLBACK, 0))
    bo = int(tr_bd.get(BREAKOUT, 0))
    br = int(tr_bd.get(BREAKOUT_RETEST, 0))

    liq_avg_m = (liq_m / liq_n) if liq_n > 0 else 0.0
    tr_avg_m = (tr_m / tr_n) if tr_n > 0 else 0.0
    liq_roi = _strategy_roi_percent_on_avg_margin(liq_net, liq_m, liq_n, ib)
    tr_roi = _strategy_roi_percent_on_avg_margin(tr_net, tr_m, tr_n, ib)

    tsp = trend_setup_realized_pnl or {}
    tsm = trend_setup_margin_usdt or {}
    pb_net = float(tsp.get(PULLBACK, 0.0))
    bo_net = float(tsp.get(BREAKOUT, 0.0))
    br_net = float(tsp.get(BREAKOUT_RETEST, 0.0))
    pb_m = float(tsm.get(PULLBACK, 0.0))
    bo_m = float(tsm.get(BREAKOUT, 0.0))
    br_m = float(tsm.get(BREAKOUT_RETEST, 0.0))
    pullback_metrics = _trend_setup_metrics_block(
        trades=pb, net_usdt=pb_net, margin_usdt=pb_m, initial_balance=ib
    )
    breakout_metrics = _trend_setup_metrics_block(
        trades=bo, net_usdt=bo_net, margin_usdt=bo_m, initial_balance=ib
    )
    breakout_retest_metrics = _trend_setup_metrics_block(
        trades=br, net_usdt=br_net, margin_usdt=br_m, initial_balance=ib
    )

    liquidity_attribution = {
        "total_trades": liq_n,
        "sweep": sweep_n,
        "margin_usdt": round(liq_m, 2),
        "avg_margin_usdt": round(liq_avg_m, 2),
        "roi_percent": liq_roi,
        "net_profit_usdt": round(liq_net, 2),
        "summary": {
            "label": "Liquidity Reversal",
            "trades": liq_n,
            "avg_margin_usdt": round(liq_avg_m, 2),
            "roi_percent": liq_roi,
            "net_profit_usdt": round(liq_net, 2),
        },
    }
    trend_attribution = {
        "total_trades": tr_n,
        PULLBACK: pb,
        BREAKOUT: bo,
        BREAKOUT_RETEST: br,
        "pullback_trades": pullback_metrics,
        "breakout_trades": breakout_metrics,
        "breakout_retest_trades": breakout_retest_metrics,
        "margin_usdt": round(tr_m, 2),
        "avg_margin_usdt": round(tr_avg_m, 2),
        "roi_percent": tr_roi,
        "net_profit_usdt": round(tr_net, 2),
        "summary": {
            "label": "Trend Following",
            "trades": tr_n,
            "pullback_trades": pullback_metrics,
            "breakout_trades": breakout_metrics,
            "breakout_retest_trades": breakout_retest_metrics,
            "avg_margin_usdt": round(tr_avg_m, 2),
            "roi_percent": tr_roi,
            "net_profit_usdt": round(tr_net, 2),
        },
    }
    return liquidity_attribution, trend_attribution


def _liquidity_attribution_summary_line(attr: dict[str, Any] | None) -> str | None:
    """Human line for reports; prefers structured ``summary``, then legacy ``summary_line``."""
    if not isinstance(attr, dict):
        return None
    s = attr.get("summary")
    if isinstance(s, dict):
        label = str(s.get("label", "Liquidity Reversal"))
        n = int(s.get("trades", attr.get("total_trades", 0)))
        avg_m = float(s.get("avg_margin_usdt", attr.get("avg_margin_usdt", 0.0)))
        roi_p = float(s.get("roi_percent", attr.get("roi_percent", 0.0)))
        net = float(s.get("net_profit_usdt", attr.get("net_profit_usdt", 0.0)))
        return (
            f"{label}: {n} trades, "
            f"Avg Margin: {avg_m:.2f} USDT, ROI: {roi_p:+.2f}%, Net Profit: {net:+.2f} USDT"
        )
    line = attr.get("summary_line")
    return str(line) if line else None


def _trend_setup_summary_segment(block: Any, fallback_trades: int = 0) -> str:
    if isinstance(block, dict):
        return (
            f"{int(block.get('trades', 0))} trades, "
            f"Avg Margin: {float(block.get('avg_margin_usdt', 0.0)):.2f} USDT, "
            f"ROI: {float(block.get('roi_percent', 0.0)):+.2f}%, "
            f"Net Profit: {float(block.get('net_profit_usdt', 0.0)):+.2f} USDT"
        )
    return f"{int(fallback_trades)} trades"


def _trend_setup_detail_line(setup_label: str, block: dict[str, Any]) -> str:
    return (
        f"   - {setup_label}: {int(block.get('trades', 0))} trades, "
        f"Avg Margin: {float(block.get('avg_margin_usdt', 0.0)):.2f} USDT, "
        f"ROI: {float(block.get('roi_percent', 0.0)):+.2f}%, "
        f"Net Profit: {float(block.get('net_profit_usdt', 0.0)):+.2f} USDT"
    )


def _trend_attribution_summary_lines(attr: dict[str, Any] | None) -> list[str]:
    if not isinstance(attr, dict):
        return []
    s = attr.get("summary")
    if isinstance(s, dict):
        label = str(s.get("label", "Trend Following"))
        n = int(s.get("trades", attr.get("total_trades", 0)))
        pb_block = s.get("pullback_trades", attr.get("pullback_trades"))
        bo_block = s.get("breakout_trades", attr.get("breakout_trades"))
        br_block = s.get("breakout_retest_trades", attr.get("breakout_retest_trades"))
        if isinstance(pb_block, dict) and isinstance(bo_block, dict):
            lines = [
                f"{label}: {n} trades:",
                _trend_setup_detail_line("Pullback", pb_block),
                _trend_setup_detail_line("Breakout", bo_block),
            ]
            if isinstance(br_block, dict):
                lines.append(_trend_setup_detail_line("Breakout Retest", br_block))
            return lines
        pb_n = int(s.get("pullback_trades", attr.get(PULLBACK, 0)))
        bo_n = int(s.get("breakout_trades", attr.get(BREAKOUT, 0)))
        avg_m = float(s.get("avg_margin_usdt", attr.get("avg_margin_usdt", 0.0)))
        roi_p = float(s.get("roi_percent", attr.get("roi_percent", 0.0)))
        net = float(s.get("net_profit_usdt", attr.get("net_profit_usdt", 0.0)))
        return [
            f"{label}: {n} trades, Pullback: {pb_n} trades, Breakout: {bo_n} trades, "
            f"Avg Margin: {avg_m:.2f} USDT, ROI: {roi_p:+.2f}%, Net Profit: {net:+.2f} USDT"
        ]
    line = attr.get("summary_line")
    return [str(line)] if line else []


def _trend_attribution_summary_line(attr: dict[str, Any] | None) -> str | None:
    lines = _trend_attribution_summary_lines(attr)
    return "\n".join(lines) if lines else None


def _normalize_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if not s:
        return ""
    if s.endswith("USDT"):
        return s
    return f"{s}USDT"


def _clear_trade_journal_for_backtest() -> None:
    """Delete everything under project ``data/position_history/``, then recreate an empty folder."""
    root = Path(__file__).resolve().parent.parent.parent / "data" / "position_history"
    if root.is_dir():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)


def _prepare_runtime_positions_for_backtest() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent
    data_file = project_root / "data" / "runtime_data" / "runtime_positions.json"
    data_file.parent.mkdir(parents=True, exist_ok=True)
    data_file.write_text("[]\n", encoding="utf-8")


def _parse_symbols_arg(raw: str) -> list[str]:
    out: list[str] = []
    for token in raw.split(","):
        s = _normalize_symbol(token)
        if s and s not in out:
            out.append(s)
    return out


def _portfolio_symbols() -> list[str]:
    """Symbols from settings that are allowed to trade (portfolio universe)."""
    out: list[str] = []
    for s in settings.SYMBOLS:
        sym = _normalize_symbol(str(s))
        if sym and sym in settings.ALLOWED_SYMBOLS and sym not in out:
            out.append(sym)
    return out


def _resolve_backtest_run_symbols(
    *,
    use_all: bool,
    portfolio_table: bool,
    only: bool,
    symbol_arg: str | None,
    portfolio_syms: list[str],
    report_symbols: list[str] | None,
) -> list[str]:
    """Pick symbols to simulate. ``--only`` + ``--symbol`` wins over ``--all``."""
    if only and report_symbols:
        return list(report_symbols)
    if use_all or (portfolio_table and not symbol_arg):
        return list(portfolio_syms)
    if report_symbols and len(portfolio_syms) > 1:
        return list(portfolio_syms)
    run_symbols = _parse_symbols_arg(symbol_arg or settings.SYMBOL or "")
    run_symbols = [_normalize_symbol(s) for s in run_symbols if _normalize_symbol(s)]
    return [s for s in run_symbols if s in settings.ALLOWED_SYMBOLS]


def _filter_result_for_report(result: dict[str, Any], report_symbols: list[str]) -> dict[str, Any]:
    """Narrow printed/JSON summary to selected symbols after a multi-coin portfolio run."""
    norm = [_normalize_symbol(s) for s in report_symbols if _normalize_symbol(s)]
    if not norm:
        return result
    per_all = result.get("per_symbol")
    if not isinstance(per_all, dict):
        return result
    filtered_per = {s: dict(per_all[s]) for s in norm if s in per_all}
    if not filtered_per:
        return result

    out = dict(result)
    out["per_symbol"] = filtered_per
    short_set = {s.replace("USDT", "") for s in norm}

    if "symbol_win_rates" in out and isinstance(out["symbol_win_rates"], dict):
        out["symbol_win_rates"] = {
            k: float(v) for k, v in out["symbol_win_rates"].items() if k in short_set
        }
    if isinstance(out.get("anti_churn"), dict):
        ac = dict(out["anti_churn"])
        entries = ac.get("entries")
        blocked = ac.get("blocked")
        if isinstance(entries, dict):
            ac["entries"] = {k: int(v) for k, v in entries.items() if k in short_set}
        if isinstance(blocked, dict):
            ac["blocked"] = {k: int(v) for k, v in blocked.items() if k in short_set}
        out["anti_churn"] = ac
    if isinstance(out.get("sizing_traces"), list):
        out["sizing_traces"] = [
            row for row in out["sizing_traces"]
            if isinstance(row, dict) and _normalize_symbol(str(row.get("symbol", ""))) in norm
        ]
    if isinstance(out.get("exit_analytics"), dict):
        ea = dict(out["exit_analytics"])
        records = ea.get("records")
        if isinstance(records, list):
            recs = [r for r in records if isinstance(r, dict) and str(r.get("symbol", "")) in short_set]
            ea["records"] = recs
            grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for row in recs:
                grouped[str(row.get("exit_reason", "unknown"))].append(row)
            by_reason: dict[str, dict[str, float]] = {}
            for reason, rows in grouped.items():
                n = float(len(rows))
                by_reason[reason] = {
                    "count": int(len(rows)),
                    "avg_hold_minutes": (sum(float(r["hold_minutes"]) for r in rows) / n) if n else 0.0,
                    "avg_mfe_proxy": (sum(float(r["mfe_proxy"]) for r in rows) / n) if n else 0.0,
                    "avg_mae_proxy": (sum(float(r["mae_proxy"]) for r in rows) / n) if n else 0.0,
                    "avg_realized_pnl": (sum(float(r["realized_pnl"]) for r in rows) / n) if n else 0.0,
                }
            ea["by_reason"] = by_reason
        out["exit_analytics"] = ea
        exit_counts: dict[str, int] = {}
        for row in ea.get("records", []):
            if isinstance(row, dict):
                reason = str(row.get("exit_reason", "unknown"))
                exit_counts[reason] = exit_counts.get(reason, 0) + 1
        out["exit_reason_counts"] = exit_counts

    sym_label = str(result.get("symbol", ""))
    if "," in sym_label:
        run_label = ", ".join(
            p.strip().replace("USDT", "") for p in sym_label.split(",") if p.strip()
        )
    else:
        run_label = ", ".join(s.replace("USDT", "") for s in sorted(per_all.keys()))
    out["portfolio_symbols"] = run_label

    if len(norm) == 1:
        sym = norm[0]
        st = filtered_per[sym]
        short = sym.replace("USDT", "")
        pnl = float(st.get("net_profit", 0.0))
        ib = float(result.get("initial_balance", 0.0))
        trades_n = int(st.get("trades", 0))
        days = max(int(result.get("days", 1)), 1)
        out["symbol"] = short
        out["total_trades"] = trades_n
        out["net_profit"] = pnl
        out["final_balance"] = ib + pnl
        out["roi"] = (pnl / ib * 100.0) if ib > 0 else float(st.get("roi", 0.0))
        out["win_rate"] = float(st.get("win_rate", 0.0))
        out["profit_factor"] = st.get("profit_factor")
        out["trades_per_day"] = trades_n / float(days)
        out = _apply_symbol_attribution_slice(out, sym)
        out["report"] = format_backtest_report(out)
        out["report_note"] = f"Portfolio simulation ({run_label.replace(', ', ',')}); stats below are for {short} only."
    else:
        out["symbol"] = ",".join(s.replace("USDT", "") for s in norm)
        total_trades = sum(int(st.get("trades", 0)) for st in filtered_per.values())
        total_pnl = sum(float(st.get("net_profit", 0.0)) for st in filtered_per.values())
        ib = float(result.get("initial_balance", 0.0))
        days = max(int(result.get("days", 1)), 1)
        out["total_trades"] = total_trades
        out["net_profit"] = total_pnl
        out["final_balance"] = ib + total_pnl
        out["roi"] = (total_pnl / ib * 100.0) if ib > 0 else 0.0
        wins = sum(
            int(round(float(st.get("win_rate", 0.0)) * int(st.get("trades", 0))))
            for st in filtered_per.values()
        )
        out["win_rate"] = (wins / total_trades) if total_trades > 0 else 0.0
        out["trades_per_day"] = total_trades / float(days)
        out["report_note"] = (
            f"Portfolio simulation ({run_label.replace(', ', ',')}); stats below are for "
            f"{out['symbol']} only."
        )
    return out


def _resolve_fetch_symbols(fetch_args: list[str] | None) -> list[str]:
    """Symbols for ``--fetch`` (empty or ``all`` → all ``settings.SYMBOLS``)."""
    if fetch_args is None:
        return []
    parts: list[str] = []
    if not fetch_args:
        return [s for s in settings.SYMBOLS if s in settings.ALLOWED_SYMBOLS]
    for token in fetch_args:
        for part in str(token).split(","):
            p = part.strip()
            if p:
                parts.append(p)
    if len(parts) == 1 and parts[0].lower() == "all":
        raw_tokens = list(settings.SYMBOLS)
    else:
        raw_tokens = []
        for part in parts:
            if part.lower() == "all":
                continue
            s = _normalize_symbol(part)
            if s:
                raw_tokens.append(s)
    out: list[str] = []
    for s in raw_tokens:
        if s in settings.ALLOWED_SYMBOLS and s not in out:
            out.append(s)
    return out


def _finalize_result(
    *,
    days: int,
    symbol_label: str,
    initial_balance: float,
    final_balance: float,
    trades: list[float],
    equity_curve: list[float],
    setup_counts: dict[str, int],
    grade_counts: dict[str, int],
    family_counts: dict[str, int],
    family_realized_pnl: dict[str, float] | None = None,
    family_margin_usdt: dict[str, float] | None = None,
    family_setup_breakdown: dict[str, Counter[str]] | None = None,
    trend_setup_realized_pnl: dict[str, float] | None = None,
    trend_setup_margin_usdt: dict[str, float] | None = None,
    per_symbol: dict[str, dict[str, float | int]] | None = None,
    ai_take_total: int = 0,
    ai_skip_total: int = 0,
    ai_skip_grade_a_total: int = 0,
    report_ai_stats: bool = False,
    exit_reason_counts: dict[str, int] | None = None,
    trades_per_hour: dict[str, int] | None = None,
    symbol_win_rates: dict[str, float] | None = None,
    anti_churn: dict[str, Any] | None = None,
    sizing_traces: list[dict[str, Any]] | None = None,
    exit_analytics: dict[str, Any] | None = None,
    trade_path_records: list[dict[str, Any]] | None = None,
    simulation_end_ts: float = 0.0,
    simulation_start_ts: float = 0.0,
    trade_metrics_windows: dict[str, dict[str, Any]] | None = None,
    per_symbol_attribution: dict[str, dict[str, Any]] | None = None,
    per_symbol_trades: dict[str, list[float]] | None = None,
) -> dict[str, Any]:
    wins = [x for x in trades if x > 0]
    losses = [x for x in trades if x < 0]
    gross_win = sum(wins)
    gross_loss = sum(losses)
    profit_factor = (gross_win / abs(gross_loss)) if gross_loss < 0 else (float("inf") if gross_win > 0 else 0.0)
    max_dd = _max_drawdown(equity_curve)
    roi = (final_balance - initial_balance) / max(initial_balance, 1e-12) * 100.0
    win_rate = (len(wins) / len(trades)) if trades else 0.0
    out = {
        "days": days,
        "symbol": symbol_label,
        "initial_balance": initial_balance,
        "final_balance": final_balance,
        "net_profit": final_balance - float(initial_balance),
        "trades": list(trades),
        "total_trades": len(trades),
        "trades_per_day": len(trades) / max(float(days), 1.0),
        "win_rate": win_rate,
        "profit_factor": None if profit_factor == float("inf") else profit_factor,
        "max_drawdown": max_dd,
        "roi": roi,
        "setup_counts": setup_counts,
        "grade_counts": grade_counts,
        "family_counts": family_counts,
    }
    ib = max(float(initial_balance), 1e-12)
    frp = dict(family_realized_pnl or {"liquidity": 0.0, TREND: 0.0})
    fm = dict(family_margin_usdt or {"liquidity": 0.0, TREND: 0.0})
    fsb = family_setup_breakdown or {"liquidity": Counter(), TREND: Counter()}
    out["family_realized_pnl"] = {
        "liquidity": float(frp.get("liquidity", 0.0)),
        TREND: float(frp.get(TREND, 0.0)),
    }
    out["family_margin_usdt"] = {
        "liquidity": round(float(fm.get("liquidity", 0.0)), 2),
        TREND: round(float(fm.get(TREND, 0.0)), 2),
    }
    out["family_setup_breakdown"] = {
        "liquidity": dict(fsb.get("liquidity", Counter())),
        TREND: dict(fsb.get(TREND, Counter())),
    }
    liq_net = float(frp.get("liquidity", 0.0))
    tr_net = float(frp.get(TREND, 0.0))
    liq_m = float(fm.get("liquidity", 0.0))
    tr_m = float(fm.get(TREND, 0.0))
    liq_n = int(family_counts.get("liquidity", 0))
    tr_n = int(family_counts.get(TREND, 0))
    out["family_avg_margin_usdt"] = {
        "liquidity": round((liq_m / liq_n) if liq_n > 0 else 0.0, 2),
        TREND: round((tr_m / tr_n) if tr_n > 0 else 0.0, 2),
    }
    out["family_roi_percent"] = {
        "liquidity": _strategy_roi_percent_on_avg_margin(liq_net, liq_m, liq_n, ib),
        TREND: _strategy_roi_percent_on_avg_margin(tr_net, tr_m, tr_n, ib),
    }
    liq_attr, tr_attr = _build_family_attribution_payload(
        family_counts=family_counts,
        family_realized_pnl=frp,
        family_margin_usdt=fm,
        family_setup_breakdown=fsb,
        initial_balance=ib,
        trend_setup_realized_pnl=trend_setup_realized_pnl,
        trend_setup_margin_usdt=trend_setup_margin_usdt,
    )
    out["liquidity_attribution"] = liq_attr
    out["trend_attribution"] = tr_attr
    if per_symbol is not None:
        out["per_symbol"] = per_symbol
    if per_symbol_attribution is not None:
        out["per_symbol_attribution"] = per_symbol_attribution
    if per_symbol_trades is not None:
        out["per_symbol_trades"] = {s: list(v) for s, v in per_symbol_trades.items()}
    if report_ai_stats:
        out["ai_take_total"] = int(ai_take_total)
        out["ai_skip_total"] = int(ai_skip_total)
        out["ai_skip_grade_a_total"] = int(ai_skip_grade_a_total)
    if exit_reason_counts is not None:
        out["exit_reason_counts"] = exit_reason_counts
    if trades_per_hour is not None:
        out["trades_per_hour"] = trades_per_hour
    if symbol_win_rates is not None:
        out["symbol_win_rates"] = symbol_win_rates
    if anti_churn is not None:
        out["anti_churn"] = anti_churn
    if sizing_traces is not None:
        out["sizing_traces"] = sizing_traces
    if exit_analytics is not None:
        out["exit_analytics"] = exit_analytics
    if trade_path_records is not None:
        out["trade_path_records"] = trade_path_records
    out["simulation_end_ts"] = float(simulation_end_ts)
    out["simulation_start_ts"] = float(simulation_start_ts)
    if trade_metrics_windows is not None:
        out["trade_metrics_windows"] = trade_metrics_windows
    out["report"] = format_backtest_report(out)
    return out


def _append_simulated_entry(
    *,
    sim_mode: str,
    ts: Any,
    sym: str,
    plan: dict[str, Any],
    strategy_family: str,
    sig: Any,
    family_counts: dict[str, int],
    family_setup_breakdown: dict[str, Counter[str]],
    family_margin_usdt: dict[str, float],
    trend_setup_margin_usdt: dict[str, float] | None = None,
    record_snapshots: list[_EntrySnapshot] | None,
    setup_counts: dict[str, int],
    grade_counts: dict[str, int],
    positions: list[Position],
    positions_per_symbol: dict[str, int],
    state: DailyState,
    opening_balance: float | None = None,
    allocation_share: float | None = None,
    vacct: VirtualAccount | None = None,
    sym_attribution: dict[str, Any] | None = None,
    entry_slippage_bps: float = 0.0,
) -> bool:
    if sim_mode != "replay_filtered":
        gate_ctx = {
            "symbol": sym,
            "entry": float(plan.get("entry", 0)),
            "stop_loss": float(plan.get("stop_loss", 0)),
            "tp1": float(plan.get("tp1", 0)),
            "setup_score": plan.get("setup_score", 0),
            "setup_grade": plan.get("setup_grade", ""),
            "confirmation_mode": plan.get("confirmation_mode", ""),
        }
        if not passes_coin_execution_gates(gate_ctx):
            return False

    grade_key = str(plan.get("setup_grade", "")).strip().upper()
    allowed_grades = [str(x).strip().upper() for x in get_coin_config(sym)["allowed_grades"]]
    if grade_key not in allowed_grades:
        return False
    setup_key = str(plan.get("setup_type", "unknown"))
    if sim_mode == "record_baseline" and record_snapshots is not None and sig is not None:
        record_snapshots.append(
            _EntrySnapshot(
                ts,
                sym,
                copy.deepcopy(plan),
                strategy_family,
                getattr(sig, "rsi", None),
                getattr(sig, "volatility", None),
            )
        )
    setup_counts[setup_key] = setup_counts.get(setup_key, 0) + 1
    grade_counts[grade_key] = grade_counts.get(grade_key, 0) + 1
    family_key = _normalize_strategy_family_key(strategy_family)
    family_counts[family_key] = int(family_counts.get(family_key, 0)) + 1
    family_setup_breakdown.setdefault(family_key, Counter())[setup_key] += 1
    lev_f = max(1.0, float(settings.LEVERAGE))
    entry_notional = float(plan.get("notional") or 0.0)
    if entry_notional <= 0.0:
        entry_notional = float(plan.get("entry", 0.0)) * float(plan.get("qty", 0.0))
    margin_added = entry_notional / lev_f
    family_margin_usdt[family_key] = float(family_margin_usdt.get(family_key, 0.0)) + margin_added
    if family_key == TREND and trend_setup_margin_usdt is not None and setup_key in (
        PULLBACK,
        BREAKOUT,
        BREAKOUT_RETEST,
    ):
        trend_setup_margin_usdt[setup_key] = float(trend_setup_margin_usdt.get(setup_key, 0.0)) + margin_added
    if sym_attribution is not None:
        _symbol_attribution_record_entry(
            sym_attribution,
            setup_key=setup_key,
            grade_key=grade_key,
            family_key=family_key,
            margin_added=margin_added,
        )
    raw_entry = float(plan["entry"])
    if entry_slippage_bps > 0:
        bps = max(0.0, float(entry_slippage_bps))
        mult = bps / 10_000.0
        if str(plan.get("direction", "")).strip().upper() == "LONG":
            entry_px = raw_entry * (1.0 + mult)
        else:
            entry_px = raw_entry * (1.0 - mult)
    else:
        entry_px = raw_entry

    open_iso = pd.Timestamp(ts).isoformat()
    risk_usd = abs(entry_px - float(plan["stop_loss"])) * float(plan["qty"])
    partial_close = plan.get("partial_close")
    if not isinstance(partial_close, list) or len(partial_close) != 3:
        partial_close = get_coin_config(sym).get("partial_close", [0.50, 0.30, 0.20])
    if vacct is not None and entry_notional > 0.0:
        vacct.record_open(entry_notional)
    positions.append(
        Position(
            symbol=sym,
            direction=plan["direction"],
            qty_total=float(plan["qty"]),
            qty_open=float(plan["qty"]),
            entry=entry_px,
            stop_loss=float(plan["stop_loss"]),
            tp1=float(plan["tp1"]),
            tp2=float(plan["tp2"]),
            tp3=float(plan["tp3"]),
            setup_type=setup_key,
            setup_grade=grade_key,
            open_time_iso=open_iso,
            initial_risk_usd=risk_usd,
            tp1_close_frac=float(partial_close[0]),
            tp2_close_frac=float(partial_close[1]),
            realized_pnl=0.0,
            strategy_family=family_key,
            market_structure=str(plan.get("market_structure", "Range")),
            market_regime_detail=plan.get("market_regime_detail"),
        )
    )
    positions_per_symbol[sym] = int(positions_per_symbol.get(sym, 0)) + 1
    state.trades += 1
    if opening_balance is not None and sim_mode != "record_baseline":
        notional = float(plan.get("notional") or 0.0)
        if notional <= 0.0:
            notional = float(plan.get("entry", 0.0)) * float(plan.get("qty", 0.0))
        open_line = format_position_open_standard_line(
            symbol=sym,
            entry=float(plan["entry"]),
            stop_loss=float(plan["stop_loss"]),
            size_usdt=notional,
            leverage=int(settings.LEVERAGE),
            risk_usdt=float(risk_usd),
            tp1=float(plan["tp1"]),
            tp2=float(plan["tp2"]),
            tp3=float(plan["tp3"]),
            price_decimals=price_rounding_decimal(sym),
            strategy_family=str(strategy_family),
            setup_type=setup_key,
        )
        risk_breakdown = plan.get("risk_breakdown") if isinstance(plan, dict) else None
        if isinstance(risk_breakdown, dict):
            log(format_risk_flow_line(sym, risk_breakdown), strip_setup=True)
        log(open_line, mode=settings.MODE, strip_setup=True)
        log_position_open(
            time_iso=open_iso,
            symbol=sym,
            direction=str(plan["direction"]),
            entry=float(plan["entry"]),
            stop_loss=float(plan["stop_loss"]),
            tp1=float(plan["tp1"]),
            tp2=float(plan["tp2"]),
            tp3=float(plan["tp3"]),
            size_usdt=notional,
            leverage=int(settings.LEVERAGE),
            risk_usdt=float(risk_usd),
            partial_close=list(float(x) for x in partial_close),
            strategy_family=str(strategy_family),
            setup_type=setup_key,
        )
    return True


def _run_portfolio_simulation(
    data: dict[str, dict[str, pd.DataFrame]],
    timeline: list[Any],
    norm_symbols: list[str],
    resolved_initial: float,
    max_open_positions: int,
    one_position_per_symbol: bool,
    days: int,
    *,
    sim_mode: str,
    record_snapshots: list[_EntrySnapshot] | None,
    replay_deque: deque[_EntrySnapshot] | None,
    injected_ai: tuple[int, int, int] | None = None,
    exit_cfg: ExitManagerConfig | None = None,
    write_daily_stat: bool = False,
    write_collect: bool = False,
) -> dict[str, Any]:
    reset_symbol_close_tracking()
    vacct = VirtualAccount(resolved_initial)
    if exit_cfg is None:
        exit_cfg = build_exit_manager_config()
    state = DailyState()
    positions: list[Position] = []
    positions_per_symbol: dict[str, int] = {s: 0 for s in norm_symbols}
    trades: list[float] = []
    equity_curve: list[float] = [vacct.balance]
    setup_counts: dict[str, int] = {}
    grade_counts: dict[str, int] = {}
    family_counts: dict[str, int] = {"liquidity": 0, TREND: 0}
    family_setup_breakdown: dict[str, Counter[str]] = {"liquidity": Counter(), TREND: Counter()}
    family_margin_usdt: dict[str, float] = {"liquidity": 0.0, TREND: 0.0}
    family_realized_pnl: dict[str, float] = {"liquidity": 0.0, TREND: 0.0}
    trend_setup_realized_pnl: dict[str, float] = {
        PULLBACK: 0.0,
        BREAKOUT: 0.0,
        BREAKOUT_RETEST: 0.0,
    }
    trend_setup_margin_usdt: dict[str, float] = {
        PULLBACK: 0.0,
        BREAKOUT: 0.0,
        BREAKOUT_RETEST: 0.0,
    }
    per_symbol_trades: dict[str, list[float]] = {s: [] for s in norm_symbols}
    per_symbol_attribution: dict[str, dict[str, Any]] = {
        s: _empty_symbol_attribution() for s in norm_symbols
    }
    per_symbol_allocations: dict[str, list[float]] = {s: [] for s in norm_symbols}
    per_symbol_entry_timestamps: dict[str, deque[float]] = {s: deque() for s in norm_symbols}
    anti_churn_blocked: dict[str, int] = {s: 0 for s in norm_symbols}
    anti_churn_entries: dict[str, int] = {s: 0 for s in norm_symbols}
    exit_reason_counts: Counter[str] = Counter()
    trades_per_hour: Counter[str] = Counter()
    exit_analytics_records: list[dict[str, Any]] = []
    sizing_traces: list[dict[str, Any]] = []
    trade_path_records: list[dict[str, Any]] = []
    pending_exit_reason: dict[int, str] = {}
    current_day = str(timeline[0].date())
    ai_take_total = 0
    ai_skip_total = 0
    ai_skip_grade_a_total = 0
    total_closed_pnl = 0.0
    exit_slippage_bps = max(0.0, float(getattr(settings, "BACKTEST_EXIT_SLIPPAGE_BPS", 0.0)))
    close_delay_bars = max(0, int(getattr(settings, "BACKTEST_CLOSE_DELAY_BARS", 0)))
    partial_fill_ratio = float(getattr(settings, "BACKTEST_PARTIAL_FILL_RATIO", 1.0))
    partial_fill_delay_bars = max(1, int(getattr(settings, "BACKTEST_PARTIAL_FILL_DELAY_BARS", 1)))
    bar_seconds = 300.0

    ds_track: dict[str, float | int] | None = None
    if write_daily_stat:
        ds_track = {
            "start": float(vacct.balance),
            "peak": float(vacct.balance),
            "max_dd_pct": 0.0,
            "wins": 0,
        }

    def _ds_bump_intrabar() -> None:
        if not write_daily_stat or ds_track is None:
            return
        b = float(vacct.balance)
        pk = max(float(ds_track["peak"]), b)
        ds_track["peak"] = pk
        if pk > 1e-9:
            dd = 100.0 * max(0.0, pk - b) / pk
            if dd > float(ds_track["max_dd_pct"]):
                ds_track["max_dd_pct"] = dd

    def _ds_flush_day(day_iso: str, st: DailyState) -> None:
        if not write_daily_stat or ds_track is None:
            return
        end_bal = float(vacct.balance)
        start_bal = float(ds_track["start"])
        dp = round(end_bal - start_bal, 2)
        pct = round(100.0 * dp / start_bal, 2) if start_bal > 1e-9 else 0.0
        snap = {
            "date": day_iso,
            "starting_balance": round(start_bal, 2),
            "ending_balance": round(end_bal, 2),
            "daily_pnl": dp,
            "daily_pnl_percent": pct,
            "total_trade": int(st.trades),
            "win": int(ds_track["wins"]),
            "loss": int(st.losses),
            "open": len(positions),
            "max_drawdown_percent": round(float(ds_track["max_dd_pct"]), 2),
            "peak_balance": round(float(ds_track["peak"]), 2),
            "trading_stopped": bool(not risk_controls_allow(st, virtual_balance=end_bal)),
        }
        risk_limit_tracking.upsert_performance_snapshot(snap)

    for ts in timeline:
        ts_utc = _normalize_timeline_ts(ts)
        day_key = str(ts_utc.date())
        if day_key != current_day:
            if write_daily_stat:
                _ds_flush_day(current_day, state)
            current_day = day_key
            state = DailyState()
            if write_daily_stat and ds_track is not None:
                b0 = float(vacct.balance)
                ds_track["start"] = b0
                ds_track["peak"] = b0
                ds_track["max_dd_pct"] = 0.0
                ds_track["wins"] = 0

        if sim_mode != "record_baseline":
            risk_limit_tracking.ensure_today(balance_usdt=float(vacct.balance), sim_date_iso=day_key)

        # Manage existing positions first.
        for pos in list(positions):
            sym = pos.symbol
            df5 = data[sym]["5m"]
            if not _sorted_dtindex_contains(df5.index, ts_utc):
                continue
            df15 = data[sym]["15m"]
            df1m = data[sym].get("1m")
            sl = build_exit_bar_slice(df5=df5, df15=df15, df1m=df1m, bar_open=ts_utc)
            if sl is None:
                continue
            bar_ts = sl.bar_ts
            high = sl.high
            low = sl.low
            close_px = sl.close_px
            current_roi = _position_roi_percent(pos, close_px)
            pos.roi_history.append({"t": bar_ts, "roi": float(current_roi)})
            if len(pos.roi_history) > 200:
                pos.roi_history = pos.roi_history[-200:]
            pos.max_roi_seen = max(float(pos.max_roi_seen), float(current_roi))
            fills: list[Any] = []
            pending_forced_close_ts = float(getattr(pos, "pending_forced_close_ts", 0.0) or 0.0)
            if pending_forced_close_ts > 0.0:
                if bar_ts >= pending_forced_close_ts and float(pos.qty_open) > 0.0:
                    pending_reason = str(getattr(pos, "pending_forced_close_reason", "TIME EXIT") or "TIME EXIT")
                    fills = _execute_forced_close_step(
                        pos=pos,
                        mark_px=float(close_px),
                        reason_tag=pending_reason,
                        partial_fill_ratio=partial_fill_ratio,
                        slippage_bps=exit_slippage_bps,
                    )
                    if float(pos.qty_open) > 0.0:
                        setattr(
                            pos,
                            "pending_forced_close_ts",
                            float(bar_ts + (float(partial_fill_delay_bars) * bar_seconds)),
                        )
                    else:
                        setattr(pos, "pending_forced_close_ts", 0.0)
                        setattr(pos, "pending_forced_close_reason", "")
                else:
                    # Wait for delayed forced-close fill; skip other exit actions this bar.
                    fills = []
            if not fills and float(getattr(pos, "pending_forced_close_ts", 0.0) or 0.0) <= 0.0:
                bar_atr = (
                    atr_from_df5(data[sym]["5m"], fallback_range=float(high) - float(low))
                    if sym in data and len(data[sym]["5m"])
                    else None
                )
            fills = apply_staged_management(
                pos,
                high=high,
                low=low,
                now_ts=bar_ts,
                pnl_fn=_pnl,
                mark_price=float(close_px),
                atr=bar_atr,
                df15=sl.candles_15m if sl is not None else None,
                sub_bars_1m=getattr(sl, "sub_bars_1m", None),
            )
            if (
                not fills
                and float(pos.qty_open) > 0
                and float(getattr(pos, "pending_forced_close_ts", 0.0) or 0.0) <= 0.0
                and bar_ts >= float(getattr(pos, "hard_stop_retry_after_ts", 0.0) or 0.0)
            ):
                hs_mark_px = float(close_px)
                hs_decision = hard_stop.evaluate_hard_stop(
                    pos=pos,
                    mark_price=float(hs_mark_px),
                    exchange_sl_active=False,
                    stop_buffer_frac=float(getattr(settings, "HARD_STOP_BUFFER_FRAC", 0.0)),
                    max_slippage_r=float(getattr(settings, "HARD_STOP_MAX_SLIPPAGE_R", 4.0)),
                )
                if hs_decision.triggered:
                    ml = float(hs_decision.max_loss_allowed_usd)
                    unreal = float(hs_decision.unrealized_pnl_at_trigger)
                    hs_mark_px = float(hs_decision.trigger_price)
                    log(
                        f"[HARD STOP] {sym} | reason={hs_decision.reason} | "
                        f"pnl={unreal:.4f} | max_loss={ml:.4f} | action=FORCE_CLOSE",
                        strip_setup=True,
                    )
                    fills = _execute_forced_close_step(
                        pos=pos,
                        mark_px=float(hs_mark_px),
                        reason_tag="HARD STOP",
                        partial_fill_ratio=1.0,
                        slippage_bps=exit_slippage_bps,
                    )
                    pos.exit_via_hard_stop = bool(float(pos.qty_open) <= 0.0)
            if not fills and pos.qty_open > 0:
                try:
                    opened_at = (
                        pd.Timestamp(pos.open_time_iso).timestamp()
                        if pos.open_time_iso
                        else bar_ts
                    )
                except Exception:
                    opened_at = bar_ts
                if bool(getattr(settings, "EXIT_PARITY_LOG", False)):
                    log_exit_input_parity(
                        mode="backtest",
                        bar_ts=bar_ts,
                        close_px=close_px,
                        candles_5m_len=len(sl.candles_5m),
                        symbol=sym,
                    )
                _bt_setup = str(getattr(pos, "setup_type", "")).strip().lower()
                _bt_direction = str(getattr(pos, "direction", "LONG")).upper()
                _bt_entry = float(getattr(pos, "entry", 0.0))
                _bt_stop = float(getattr(pos, "stop_loss", 0.0))
                _bt_breakout_level = None
                if _bt_setup in (BREAKOUT, BREAKOUT_RETEST) and _bt_entry > 0.0 and _bt_stop > 0.0:
                    _bt_risk = abs(_bt_entry - _bt_stop)
                    if _bt_direction == "LONG":
                        _bt_breakout_level = _bt_entry - _bt_risk * 0.5
                    else:
                        _bt_breakout_level = _bt_entry + _bt_risk * 0.5
                decision = decide_exit_from_bar_slice(
                    slice_=sl,
                    time_in_trade=max(0.0, bar_ts - opened_at),
                    current_roi=float(current_roi),
                    roi_history=list(pos.roi_history),
                    max_roi_seen=float(pos.max_roi_seen),
                    exit_manager=exit_cfg,
                    direction=str(pos.direction),
                    time_since_tp1=(
                        max(0.0, bar_ts - float(pos.tp1_hit_at_ts))
                        if pos.tp1_hit_at_ts is not None
                        else None
                    ),
                    symbol=str(sym),
                    decide_exit_fn=decide_exit,
                    entry_price=_bt_entry,
                    breakout_level=_bt_breakout_level,
                )
                if str(decision.get("action", "HOLD")).upper() == "CLOSE":
                    exit_reason = str(decision.get("reason", "TIME EXIT"))
                    immediate_exit = is_immediate_forced_exit_reason(exit_reason)
                    fill_ratio = 1.0 if immediate_exit else partial_fill_ratio
                    if close_delay_bars > 0 and not immediate_exit:
                        if float(getattr(pos, "pending_forced_close_ts", 0.0) or 0.0) <= 0.0:
                            setattr(
                                pos,
                                "pending_forced_close_ts",
                                float(bar_ts + (float(close_delay_bars) * bar_seconds)),
                            )
                            setattr(pos, "pending_forced_close_reason", "TIME EXIT")
                            if settings.should_log_exit_debug_trace():
                                log(
                                    f"[EXIT DECISION] {sym} | Action: CLOSE | delayed_close_bars={close_delay_bars}",
                                    strip_setup=True,
                                )
                    else:
                        fills = _execute_forced_close_step(
                            pos=pos,
                            mark_px=float(close_px),
                            reason_tag="TIME EXIT",
                            partial_fill_ratio=fill_ratio,
                            slippage_bps=exit_slippage_bps,
                        )
                    if settings.should_log_exit_debug_trace():
                        log(
                            format_exit_decision_close_line(
                                sym,
                                str(decision.get("reason", "")),
                                metrics=decision.get("metrics"),
                                current_roi=float(current_roi),
                                max_roi_seen=float(pos.max_roi_seen),
                            ),
                            strip_setup=True,
                        )
                    pending_exit_reason[id(pos)] = str(decision.get("reason", "TIME EXIT"))
            norm_fills = []
            for fill in fills:
                if isinstance(fill, dict):
                    norm_fills.append(fill)
                else:
                    norm_fills.append(
                        {
                            "tag": fill.tag,
                            "price": float(fill.price),
                            "qty_closed": float(fill.qty_closed),
                            "qty_remaining": float(fill.qty_remaining),
                            "pnl": float(fill.pnl),
                        }
                    )
            fills = norm_fills
            price_dp_bt = price_rounding_decimal(pos.symbol)
            for fill in fills:
                # "CLOSE" carries cumulative trade PnL for reporting; do not
                # apply it to account balance/risk again.
                if fill["tag"] != "CLOSE":
                    vacct.apply_realized_pnl(fill["pnl"], float(fill["qty_closed"]) * float(pos.entry))
                    state.daily_pnl += float(fill["pnl"])
                if fill["tag"] != "CLOSE" and str(fill.get("tag", "")).upper() != "TIME EXIT":
                    px_s = format_price(float(fill["price"]), price_dp_bt)
                    qty_closed_v = round_qty(float(fill["qty_closed"]), 3)
                    qty_rem_v = round_qty(float(fill["qty_remaining"]), 3)
                    pnl_v = round_usd(float(fill["pnl"]), 2)
                    log(
                        f"[{fill['tag']}] {sym} | price={px_s} | "
                        f"qty_closed={qty_closed_v:.3f} | qty_remaining={qty_rem_v:.3f} | "
                        f"pnl={pnl_v:+.2f}",
                        strip_setup=True,
                    )
                    if str(fill.get("tag", "")).upper() == "TP1 HIT" and not bool(
                        getattr(pos, "hit_tp2", False)
                    ):
                        log_tp1_breakeven_memory(pos, qty_remaining=float(fill["qty_remaining"]))
                if fill["tag"] == "CLOSE":
                    assert pos.qty_open <= 1e-12
                    record_symbol_close_bar(sym, float(bar_ts))
                    close_iso = ts_utc.isoformat()
                    dur = duration_minutes(pos.open_time_iso, close_iso)
                    if not pos.close_journal_logged:
                        trade_pnl = float(pos.realized_pnl)
                        total_closed_pnl += trade_pnl
                        tags_upper = {str(f["tag"]).upper() for f in fills}
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
                            balance_usdt=float(vacct.balance),
                            tp1_hit=bool(pos.hit_tp1),
                            tp2_hit=bool(pos.hit_tp2),
                            tp3_hit=bool(pos.hit_tp3),
                            closed_reason=infer_journal_closed_reason(tags_upper),
                            strategy_family=str(getattr(pos, "strategy_family", "liquidity")),
                            setup_type=str(getattr(pos, "setup_type", "unknown")),
                        )
                        log(
                            format_close_console_line(
                                symbol=pos.symbol,
                                size_usdt=float(pos.entry) * float(pos.qty_total),
                                leverage=int(settings.LEVERAGE),
                                entry=float(pos.entry),
                                exit_px=float(fill["price"]),
                                duration_minutes_val=dur,
                                final_pnl=trade_pnl,
                                price_decimals=price_dp_bt,
                            ),
                            strip_setup=True,
                        )
                        pos.close_journal_logged = True
                    else:
                        trade_pnl = float(pos.realized_pnl)
                    trades.append(trade_pnl)
                    fam_attr = str(getattr(pos, "strategy_family", "liquidity") or "liquidity")
                    if fam_attr not in ("liquidity", TREND):
                        fam_attr = _normalize_strategy_family_key(fam_attr)
                    family_realized_pnl[fam_attr] = float(family_realized_pnl.get(fam_attr, 0.0)) + float(
                        trade_pnl
                    )
                    if fam_attr == TREND:
                        setup_key = str(getattr(pos, "setup_type", "")).strip().lower()
                        if setup_key in trend_setup_realized_pnl:
                            trend_setup_realized_pnl[setup_key] = float(
                                trend_setup_realized_pnl.get(setup_key, 0.0)
                            ) + float(trade_pnl)
                    if sym in per_symbol_attribution:
                        _symbol_attribution_record_close(
                            per_symbol_attribution[sym],
                            family_attr=fam_attr,
                            setup_type=str(getattr(pos, "setup_type", "")),
                            trade_pnl=float(trade_pnl),
                        )
                    per_symbol_trades[sym].append(trade_pnl)
                    close_reason = pending_exit_reason.pop(id(pos), "")
                    if not close_reason:
                        close_reason = "Unknown"
                        if any(str(f.get("tag", "")).upper().startswith("SL") for f in fills):
                            close_reason = "SL"
                        elif any("HARD STOP" in str(f.get("tag", "")).upper() for f in fills):
                            close_reason = "HARD STOP"
                        elif any("TIME EXIT" in str(f.get("tag", "")).upper() for f in fills):
                            close_reason = "TIME EXIT"
                        elif any(str(f.get("tag", "")).upper().startswith("TP3") for f in fills):
                            close_reason = "TP3"
                        elif any(str(f.get("tag", "")).upper().startswith("TP2") for f in fills):
                            close_reason = "TP2_CLOSE"
                        elif any(str(f.get("tag", "")).upper().startswith("TP1") for f in fills):
                            close_reason = "TP1_CLOSE"
                        elif any(str(f.get("tag", "")).upper() == "CLOSE" for f in fills):
                            # Defensive fallback: we closed but no explicit lifecycle tag survived.
                            close_reason = "CLOSE"
                    tags_upper = [str(f.get("tag", "")).upper() for f in fills]
                    sl_hit = any("SL HIT" in tu for tu in tags_upper) or str(close_reason).strip().upper() == "SL"
                    time_exit = any("TIME EXIT" in tu for tu in tags_upper)
                    trade_path_records.append(
                        {
                            "close_ts": float(ts_utc.timestamp()),
                            "tp1_hit": bool(pos.hit_tp1),
                            "tp2_hit": bool(pos.hit_tp2),
                            "tp3_hit": bool(pos.hit_tp3),
                            "sl_hit": bool(sl_hit),
                            "time_exit": bool(time_exit),
                            "exit_reason": str(close_reason),
                            "realized_pnl": float(trade_pnl),
                        }
                    )
                    exit_reason_counts[close_reason] += 1
                    trades_per_hour[ts_utc.strftime("%H")] += 1
                    roi_vals = [float(p.get("roi", 0.0)) for p in list(pos.roi_history)]
                    exit_analytics_records.append(
                        {
                            "symbol": sym.replace("USDT", ""),
                            "exit_reason": close_reason,
                            "hold_minutes": float(dur),
                            "mfe_proxy": max(roi_vals) if roi_vals else 0.0,
                            "mae_proxy": min(roi_vals) if roi_vals else 0.0,
                            "realized_pnl": float(trade_pnl),
                        }
                    )
                    try:
                        opened_dt_bt = pd.Timestamp(pos.open_time_iso).to_pydatetime()
                        closed_dt_bt = ts_utc.to_pydatetime() if hasattr(ts_utc, 'to_pydatetime') else ts_utc
                        result = collect_regime_for_trade(
                            data[sym]["1h"], data[sym].get("15m"), data[sym]["5m"], sym,
                            opened_dt_bt, closed_dt_bt,
                            {
                                "side": pos.direction,
                                "entry": pos.entry,
                                "stop_loss": pos.stop_loss,
                                "pnl": trade_pnl,
                                "strategy_setup": getattr(pos, "setup_type", "unknown"),
                                "bars_held": max(1, round(dur / 5.0)),
                                "tp_hit": bool(pos.hit_tp1 or pos.hit_tp2 or pos.hit_tp3),
                                "tp1_hit": bool(pos.hit_tp1),
                                "tp2_hit": bool(pos.hit_tp2),
                                "tp3_hit": bool(pos.hit_tp3),
                                "closed_reason": close_reason,
                                "market_structure": getattr(pos, "market_structure", "Range"),
                                "market_regime_detail": getattr(pos, "market_regime_detail", None),
                            },
                            write_to_disk=write_collect,
                        )
                        if result is None:
                            print(f"[TRACE] {sym} | PnL={trade_pnl:.4f} | collect_regime_for_trade returned None")
                    except Exception as exc:
                        print(f"[TRACE] {sym} | Exception in collect_regime_for_trade: {exc}")
                    state.losses += 1 if trade_pnl < 0 else 0
                    if write_daily_stat and ds_track is not None and float(trade_pnl) > 0:
                        ds_track["wins"] = int(ds_track["wins"]) + 1
                    state.loss_streak = (state.loss_streak + 1) if trade_pnl < 0 else 0
                    if sim_mode != "record_baseline":
                        risk_limit_tracking.record_full_position_close(
                            exchange_pnl_usdt=None,
                            internal_realized_pnl_usdt=float(trade_pnl),
                            journal_balance_usdt=float(vacct.balance),
                            max_losses_per_day=int(settings.MAX_LOSSES_PER_DAY),
                            sim_date_iso=day_key,
                        )
                    positions.remove(pos)
                    positions_per_symbol[sym] = max(0, int(positions_per_symbol.get(sym, 0)) - 1)
                    break

        # Evaluate fresh entries with shared balance and global open-position cap.
        if sim_mode != "record_baseline":
            rl_ok_bt, _rl_reason_bt = risk_limit_tracking.risk_file_entry_gate(
                balance_usdt=float(vacct.balance),
                sim_date_iso=day_key,
            )
            if not rl_ok_bt:
                equity_curve.append(vacct.balance)
                _ds_bump_intrabar()
                continue
        if not risk_controls_allow(state, virtual_balance=vacct.balance):
            equity_curve.append(vacct.balance)
            _ds_bump_intrabar()
            continue

        if sim_mode == "replay_filtered":
            for sym in norm_symbols:
                if one_position_per_symbol and symbol_at_per_symbol_cap(sym, positions_per_symbol):
                    continue
                if len(positions) >= max_open_positions:
                    break

                df5 = data[sym]["5m"]
                if not _sorted_dtindex_contains(df5.index, ts_utc):
                    continue
                d1h = _slice_asof_tail_reset_index(data[sym]["1h"], ts, 420, ts_utc=ts_utc)
                d15 = _slice_asof_tail_reset_index(
                    data[sym]["15m"], ts, max(200, settings.ATR_REGIME_LOOKBACK + 24), ts_utc=ts_utc
                )
                d5 = _slice_asof_tail_reset_index(
                    df5, ts, liquidity_scan_5m_bars(), ts_utc=ts_utc
                )

                sig = None
                strategy_family = PULLBACK
                if replay_deque is None or not replay_deque:
                    continue
                head = replay_deque[0]
                if head.ts != ts or head.sym != sym:
                    continue
                now_unix = float(ts_utc.timestamp())
                bucket = per_symbol_entry_timestamps[sym]
                while bucket and (now_unix - float(bucket[0])) > 3600.0:
                    bucket.popleft()
                if len(bucket) >= 3:
                    anti_churn_blocked[sym] += 1
                    log(f"[ANTI-CHURN] {sym} | blocked entry | rolling_60m_entries={len(bucket)}")
                    continue
                snap = replay_deque.popleft()
                plan = snap.plan
                strategy_family = snap.strategy_family
                opened = _append_simulated_entry(
                    sim_mode=sim_mode,
                    ts=ts,
                    sym=sym,
                    plan=plan,
                    strategy_family=strategy_family,
                    sig=sig,
                    family_counts=family_counts,
                    family_setup_breakdown=family_setup_breakdown,
                    family_margin_usdt=family_margin_usdt,
                    trend_setup_margin_usdt=trend_setup_margin_usdt,
                    record_snapshots=record_snapshots,
                    setup_counts=setup_counts,
                    grade_counts=grade_counts,
                    positions=positions,
                    positions_per_symbol=positions_per_symbol,
                    state=state,
                    opening_balance=vacct.balance,
                    allocation_share=None,
                    vacct=vacct,
                    sym_attribution=per_symbol_attribution.get(sym),
                    entry_slippage_bps=exit_slippage_bps,
                )
                if opened:
                    bucket.append(now_unix)
                    anti_churn_entries[sym] += 1
                    if sim_mode != "record_baseline":
                        risk_limit_tracking.record_new_open(
                            balance_usdt=float(vacct.balance), sim_date_iso=day_key
                        )
                    if isinstance(plan, dict) and isinstance(plan.get("sizing_trace"), dict):
                        sizing_traces.append(
                            {"symbol": sym, "time": ts_utc.isoformat(), **dict(plan["sizing_trace"])}
                        )
                    per_symbol_allocations[sym].append(float(plan.get("notional", 0.0)))
        else:
            if len(positions) >= max_open_positions:
                equity_curve.append(vacct.balance)
                _ds_bump_intrabar()
                continue

            candidates: list[tuple[str, Any, Any, Any, Any, float]] = []
            for sym in norm_symbols:
                df5 = data[sym]["5m"]
                if not _sorted_dtindex_contains(df5.index, ts_utc):
                    continue
                now_unix = float(ts_utc.timestamp())
                bucket = per_symbol_entry_timestamps[sym]
                while bucket and (now_unix - float(bucket[0])) > 3600.0:
                    bucket.popleft()
                if len(bucket) >= 3:
                    anti_churn_blocked[sym] += 1
                    log(f"[ANTI-CHURN] {sym} | blocked entry | rolling_60m_entries={len(bucket)}")
                    continue
                d1h = _slice_asof_tail_reset_index(data[sym]["1h"], ts, 420, ts_utc=ts_utc)
                d15 = _slice_asof_tail_reset_index(
                    data[sym]["15m"], ts, max(200, settings.ATR_REGIME_LOOKBACK + 24), ts_utc=ts_utc
                )
                d5 = _slice_asof_tail_reset_index(
                    df5, ts, liquidity_scan_5m_bars(), ts_utc=ts_utc
                )

                latest_closed_ts = _latest_closed_5m_candle_ts(d5)
                min_bars = resolve_bars_since_last_close_min(sym)
                bars_since: int | None = count_bars_since_close_5m(
                    latest_closed_bar_ts=latest_closed_ts,
                    last_close_bar_ts=get_last_close_bar_ts(sym),
                )
                if (
                    min_bars > 0
                    and bars_since is not None
                    and int(bars_since) < int(min_bars)
                ):
                    log_entry_after_bars_skip(
                        sym, int(bars_since), int(min_bars), strip_setup=True
                    )
                    continue
                sig = get_signal(
                    d1h,
                    d15,
                    d5,
                    symbol=sym,
                    bars_since_last_close=bars_since,
                )
                if sig is None:
                    continue
                regime_risk_multiplier, skip_reason = compute_regime_risk_multiplier(sym, d15, d5)
                if is_skip_reason_insufficient_data(skip_reason):
                    continue
                candidates.append((sym, sig, d1h, d15, d5, regime_risk_multiplier))

            strength_scores = {s: 0.0 for s in norm_symbols}
            for sym, sig, _d1h, _d15, _d5, _rm in candidates:
                strength_scores[sym] = float(compute_strength(sig.setup_grade))
            weights = compute_weights(strength_scores)

            candidates.sort(key=lambda r: weights.get(r[0], 0.0), reverse=True)

            for sym, sig, d1h, d15, d5, regime_risk_multiplier in candidates:
                if len(positions) >= max_open_positions:
                    break
                if one_position_per_symbol and symbol_entry_blocked(
                    sym,
                    positions_per_symbol,
                    setup_type=str(getattr(sig, "setup_type", "")),
                    direction=str(getattr(sig, "direction", "")),
                    strategy_family=str(getattr(sig, "strategy_family", "")),
                    open_positions=positions,
                ):
                    continue
                w = float(weights.get(sym, 0.0))
                if w <= 0:
                    continue

                if LOSS_FILTER:
                    try:
                        from types import SimpleNamespace

                        setup = str(getattr(sig, "setup_type", "")).strip().lower()
                        regime_dict = getattr(sig, "market_regime_detail", None) or {}

                        if setup == BREAKOUT:
                            shim = SimpleNamespace(
                                regime=regime_dict.get("regime", ""),
                                adx=regime_dict.get("adx", 0),
                            )
                            allow, reasons = breakout_filter(shim)
                        elif setup in (LIQUIDITY_SWEEP_REVERSAL, "liquidity"):
                            vol = d15["volume"].astype(float)
                            vol_ratio = float(vol.iloc[-1]) / max(float(vol.iloc[-20:].mean()), 1e-12)
                            shim = SimpleNamespace(
                                atr_percentile=regime_dict.get("atr_percentile", 50),
                                volume_ratio=vol_ratio,
                            )
                            allow, reasons = sweep_filter(shim)
                        else:
                            allow, reasons = True, []

                        if not allow:
                            reason_str = "; ".join(reasons) if reasons else "filter"
                            log(f"[SKIP] {sym} | Filter: {reason_str}")
                            continue
                    except Exception:
                        pass

                open_n = positions_open_notional(positions)
                available = portfolio_available_balance(vacct, positions)
                account_notional_cap = available * max(1.0, float(settings.LEVERAGE))
                plan = build_order_plan(
                    sig,
                    balance=vacct.balance,
                    positions_per_symbol=positions_per_symbol,
                    open_positions_total=len(positions),
                    allocation_share=1.0,
                    symbol=sym,
                    max_open_positions=max_open_positions,
                    virtual=vacct,
                    open_notional_total=open_n,
                    regime_risk_multiplier=regime_risk_multiplier,
                    data_15m=d15,
                    max_notional_account_cap=account_notional_cap,
                    available_balance=available,
                    open_positions=positions,
                )
                if not isinstance(plan, dict):
                    continue
                lev_f = max(1.0, float(settings.LEVERAGE))
                margin_needed = float(plan.get("notional", 0.0)) / lev_f
                if margin_needed > available + 1e-9:
                    continue
                strategy_family = sig.strategy_family
                opened = _append_simulated_entry(
                    sim_mode=sim_mode,
                    ts=ts,
                    sym=sym,
                    plan=plan,
                    strategy_family=strategy_family,
                    sig=sig,
                    family_counts=family_counts,
                    family_setup_breakdown=family_setup_breakdown,
                    family_margin_usdt=family_margin_usdt,
                    trend_setup_margin_usdt=trend_setup_margin_usdt,
                    record_snapshots=record_snapshots,
                    setup_counts=setup_counts,
                    grade_counts=grade_counts,
                    positions=positions,
                    positions_per_symbol=positions_per_symbol,
                    state=state,
                    opening_balance=vacct.balance,
                    allocation_share=1.0,
                    vacct=vacct,
                    sym_attribution=per_symbol_attribution.get(sym),
                    entry_slippage_bps=exit_slippage_bps,
                )
                if opened:
                    bucket.append(now_unix)
                    anti_churn_entries[sym] += 1
                    if sim_mode != "record_baseline":
                        risk_limit_tracking.record_new_open(
                            balance_usdt=float(vacct.balance), sim_date_iso=day_key
                        )
                    if isinstance(plan, dict) and isinstance(plan.get("sizing_trace"), dict):
                        sizing_traces.append(
                            {"symbol": sym, "time": ts_utc.isoformat(), **dict(plan["sizing_trace"])}
                        )
                    per_symbol_allocations[sym].append(float(plan.get("notional", 0.0)))

        equity_curve.append(vacct.balance)
        _ds_bump_intrabar()

    if write_daily_stat:
        _ds_flush_day(current_day, state)

    if sim_mode == "replay_filtered" and replay_deque is not None and len(replay_deque) > 0:
        raise RuntimeError(
            f"AI replay desync: {len(replay_deque)} baseline entries were not consumed (timeline/symbol order mismatch)"
        )

    if injected_ai is not None:
        ai_take_total, ai_skip_total, ai_skip_grade_a_total = injected_ai

    per_symbol: dict[str, dict[str, float | int]] = {}
    for sym in norm_symbols:
        sym_trades = per_symbol_trades[sym]
        sym_wins = [x for x in sym_trades if x > 0]
        sym_losses = [x for x in sym_trades if x < 0]
        gross_win = sum(sym_wins)
        gross_loss = sum(sym_losses)
        sym_pf = (gross_win / abs(gross_loss)) if gross_loss < 0 else (float("inf") if gross_win > 0 else 0.0)
        sym_pnl = float(sum(sym_trades))
        sym_allocs = per_symbol_allocations[sym]
        sym_peak_alloc = float(max(sym_allocs)) if sym_allocs else 0.0
        sym_avg_alloc = (float(sum(sym_allocs)) / float(len(sym_allocs))) if sym_allocs else 0.0
        sym_roi = (sym_pnl / sym_avg_alloc * 100.0) if sym_avg_alloc != 0.0 else 0.0
        per_symbol[sym] = {
            "trades": len(sym_trades),
            "net_profit": sym_pnl,
            "capital": sym_peak_alloc,
            "roi": sym_roi,
            "avg_alloc": sym_avg_alloc,
            "win_rate": (len(sym_wins) / len(sym_trades)) if sym_trades else 0.0,
            "profit_factor": None if sym_pf == float("inf") else sym_pf,
        }

    label = ",".join(s.replace("USDT", "") for s in norm_symbols)
    symbol_win_rates = {
        s.replace("USDT", ""): (
            (len([x for x in per_symbol_trades[s] if x > 0]) / len(per_symbol_trades[s]))
            if per_symbol_trades[s]
            else 0.0
        )
        for s in norm_symbols
    }
    anti_churn = {
        "window_minutes": 60,
        "max_entries_per_window": 3,
        "entries": {k.replace("USDT", ""): int(v) for k, v in anti_churn_entries.items()},
        "blocked": {k.replace("USDT", ""): int(v) for k, v in anti_churn_blocked.items()},
    }
    exit_analytics_by_reason: dict[str, dict[str, float]] = {}
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in exit_analytics_records:
        grouped[str(row.get("exit_reason", "unknown"))].append(row)
    for reason, rows in grouped.items():
        n = float(len(rows))
        exit_analytics_by_reason[reason] = {
            "count": int(len(rows)),
            "avg_hold_minutes": (sum(float(r["hold_minutes"]) for r in rows) / n) if n else 0.0,
            "avg_mfe_proxy": (sum(float(r["mfe_proxy"]) for r in rows) / n) if n else 0.0,
            "avg_mae_proxy": (sum(float(r["mae_proxy"]) for r in rows) / n) if n else 0.0,
            "avg_realized_pnl": (sum(float(r["realized_pnl"]) for r in rows) / n) if n else 0.0,
        }
    simulation_end_ts = float(pd.Timestamp(timeline[-1]).timestamp()) if timeline else 0.0
    simulation_start_ts = float(pd.Timestamp(timeline[0]).timestamp()) if timeline else 0.0
    trade_metrics_windows = _trade_metrics_for_standard_windows(
        trade_path_records,
        end_ts=simulation_end_ts,
        start_ts=simulation_start_ts,
        sim_days=int(days),
    )
    return _finalize_result(
        days=days,
        symbol_label=label,
        initial_balance=resolved_initial,
        final_balance=vacct.balance,
        trades=trades,
        equity_curve=equity_curve,
        setup_counts=setup_counts,
        grade_counts=grade_counts,
        family_counts=family_counts,
        family_realized_pnl=family_realized_pnl,
        family_margin_usdt=family_margin_usdt,
        family_setup_breakdown=family_setup_breakdown,
        trend_setup_realized_pnl=trend_setup_realized_pnl,
        trend_setup_margin_usdt=trend_setup_margin_usdt,
        per_symbol=per_symbol,
        ai_take_total=ai_take_total,
        ai_skip_total=ai_skip_total,
        ai_skip_grade_a_total=ai_skip_grade_a_total,
        report_ai_stats=injected_ai is not None,
        exit_reason_counts=dict(exit_reason_counts),
        trades_per_hour=dict(trades_per_hour),
        symbol_win_rates=symbol_win_rates,
        anti_churn=anti_churn,
        sizing_traces=sizing_traces,
        exit_analytics={"records": exit_analytics_records, "by_reason": exit_analytics_by_reason},
        trade_path_records=trade_path_records,
        simulation_end_ts=simulation_end_ts,
        simulation_start_ts=simulation_start_ts,
        trade_metrics_windows=trade_metrics_windows,
        per_symbol_attribution=_serialize_per_symbol_attribution(per_symbol_attribution),
        per_symbol_trades=per_symbol_trades,
    )


def run_portfolio_backtest(
    symbols: list[str],
    *,
    days: int,
    initial_balance: float | None = None,
    max_open_positions: int = settings.MAX_OPEN_POSITIONS,
    one_position_per_symbol: bool = True,
    use_ai: bool = False,
    apply_exit_tuning: bool | None = None,
    write_daily_stat: bool = False,
    file_log: bool = False,
    write_collect: bool = False,
) -> dict[str, Any]:
    set_backtest_file_logging(bool(file_log))
    try:
        if file_log:
            reset_backtest_logs_for_new_run()
        norm_symbols = [_normalize_symbol(s) for s in symbols if _normalize_symbol(s)]
        if not norm_symbols:
            raise RuntimeError("No valid symbols for portfolio backtest")
        norm_symbols = [s for s in norm_symbols if s in settings.ALLOWED_SYMBOLS]
        if not norm_symbols:
            raise Exception("No allowed symbols to trade")

        _clear_trade_journal_for_backtest()
        _prepare_runtime_positions_for_backtest()

        data: dict[str, dict[str, pd.DataFrame]] = {}
        all_ts: set[pd.Timestamp] = set()
        for sym in norm_symbols:
            df5 = _fetch_klines(sym, "5m", days)
            df15 = _fetch_klines(sym, "15m", max(days, 30))
            df1h = _fetch_klines(sym, "1h", max(days, 60))
            df1m = _fetch_klines(sym, "1m", days)
            if len(df5) < 250 or len(df15) < 120 or len(df1h) < 250:
                raise RuntimeError(f"Not enough historical data to run backtest for {sym}")
            data[sym] = {
                "1m": df1m.set_index("timestamp"),
                "5m": df5.set_index("timestamp"),
                "15m": df15.set_index("timestamp"),
                "1h": df1h.set_index("timestamp"),
            }
            all_ts.update(df5["timestamp"].iloc[220:].tolist())

        _materialize_backtest_timestamp_columns(data)
        _precompute_indicator_columns(data)

        timeline = sorted(all_ts)
        if not timeline:
            raise RuntimeError("No timeline data to run portfolio backtest")

        resolved_initial = (
            float(initial_balance) if initial_balance is not None else float(settings.INITIAL_CAPITAL)
        )
        use_exit_tuning = (
            bool(apply_exit_tuning)
            if apply_exit_tuning is not None
            else bool(getattr(settings, "APPLY_EXIT_TUNING", False))
        )
        cfg = build_exit_manager_config(apply_tuning=use_exit_tuning)

        if use_ai:
            recorded: list[_EntrySnapshot] = []
            _run_portfolio_simulation(
                data,
                timeline,
                norm_symbols,
                resolved_initial,
                max_open_positions,
                one_position_per_symbol,
                days,
                sim_mode="record_baseline",
                record_snapshots=recorded,
                replay_deque=None,
                injected_ai=None,
                exit_cfg=cfg,
                write_daily_stat=False,
                write_collect=write_collect,
            )
            filtered, at, sk, ska = _filter_snapshots_with_ai(recorded)
            return _run_portfolio_simulation(
                data,
                timeline,
                norm_symbols,
                resolved_initial,
                max_open_positions,
                one_position_per_symbol,
                days,
                sim_mode="replay_filtered",
                record_snapshots=None,
                replay_deque=deque(filtered),
                injected_ai=(at, sk, ska),
                exit_cfg=cfg,
                write_daily_stat=write_daily_stat,
                write_collect=write_collect,
            )

        return _run_portfolio_simulation(
            data,
            timeline,
            norm_symbols,
            resolved_initial,
            max_open_positions,
            one_position_per_symbol,
            days,
            sim_mode="normal",
            record_snapshots=None,
            replay_deque=None,
            injected_ai=None,
            exit_cfg=cfg,
            write_daily_stat=write_daily_stat,
            write_collect=write_collect,
        )
    finally:
        flush_backtest_log_buffer()
        set_backtest_file_logging(False)


def run_backtest(
    days: int,
    initial_balance: float | None = None,
    symbol: str | None = None,
    *,
    file_log: bool = False,
    write_daily_stat: bool = False,
) -> dict[str, Any]:
    return run_portfolio_backtest(
        [_normalize_symbol(symbol or settings.SYMBOL)],
        days=days,
        initial_balance=initial_balance,
        max_open_positions=1,
        one_position_per_symbol=True,
        file_log=file_log,
        write_daily_stat=write_daily_stat,
    )


def _trend_following_artifact_block(
    ta: dict[str, Any],
    fc_a: dict[str, Any],
    froi_a: dict[str, float],
) -> dict[str, Any]:
    """Serialize trend_following metrics for backtest_result.json (per-setup blocks)."""
    pb_block = ta.get("pullback_trades")
    bo_block = ta.get("breakout_trades")
    br_block = ta.get("breakout_retest_trades")
    if not isinstance(pb_block, dict):
        pb_block = _trend_setup_metrics_block(
            trades=int(ta.get(PULLBACK, 0)),
            net_usdt=0.0,
            margin_usdt=0.0,
            initial_balance=1.0,
        )
    if not isinstance(bo_block, dict):
        bo_block = _trend_setup_metrics_block(
            trades=int(ta.get(BREAKOUT, 0)),
            net_usdt=0.0,
            margin_usdt=0.0,
            initial_balance=1.0,
        )
    if not isinstance(br_block, dict):
        br_block = _trend_setup_metrics_block(
            trades=int(ta.get(BREAKOUT_RETEST, 0)),
            net_usdt=0.0,
            margin_usdt=0.0,
            initial_balance=1.0,
        )
    return {
        "trades": int(ta.get("total_trades", fc_a.get(TREND, 0))),
        "margin_usdt": float(ta.get("margin_usdt", 0.0)),
        "avg_margin_usdt": float(ta.get("avg_margin_usdt", 0.0)),
        "roi_percent": float(ta.get("roi_percent", froi_a.get(TREND, 0.0))),
        "net_profit_usdt": float(ta.get("net_profit_usdt", 0.0)),
        "pullback_trades": pb_block,
        "breakout_trades": bo_block,
        "breakout_retest_trades": br_block,
    }


def _backtest_day_window_payload(result: dict[str, Any]) -> dict[str, Any]:
    """KPI block for one backtest window (portfolio or symbol-filtered result)."""
    profit_factor_raw = result.get("profit_factor")
    fc_a = result.get("family_counts") if isinstance(result.get("family_counts"), dict) else {}
    froi_a = result.get("family_roi_percent") if isinstance(result.get("family_roi_percent"), dict) else {}
    la = result.get("liquidity_attribution") if isinstance(result.get("liquidity_attribution"), dict) else {}
    ta = result.get("trend_attribution") if isinstance(result.get("trend_attribution"), dict) else {}
    return {
        "roi_percent": round(float(result.get("roi", 0.0)), 2),
        "total_trades": int(result.get("total_trades", 0)),
        "trades_per_day": round(float(result.get("trades_per_day", 0.0)), 2),
        "win_rate_percent": round(float(result.get("win_rate", 0.0)) * 100.0, 2),
        "profit_factor": (
            None if profit_factor_raw is None else round(float(profit_factor_raw), 2)
        ),
        "max_drawdown_percent": round(float(result.get("max_drawdown", 0.0)) * 100.0, 2),
        "liquidity_reversal": {
            "trades": int(la.get("total_trades", fc_a.get("liquidity", 0))),
            "sweep_trades": int(la.get("sweep", 0)),
            "margin_usdt": float(la.get("margin_usdt", 0.0)),
            "avg_margin_usdt": float(la.get("avg_margin_usdt", 0.0)),
            "roi_percent": float(la.get("roi_percent", froi_a.get("liquidity", 0.0))),
            "net_profit_usdt": float(la.get("net_profit_usdt", 0.0)),
        },
        "trend_following": _trend_following_artifact_block(ta, fc_a, froi_a),
    }


def _backtest_symbol_day_window_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Symbol-filtered window: portfolio KPIs plus setup/grade breakdown from --symbol report."""
    payload = dict(_backtest_day_window_payload(result))
    setup_counts = result.get("setup_counts")
    grade_counts = result.get("grade_counts")
    if isinstance(setup_counts, dict):
        payload["setup_counts"] = {str(k): int(v) for k, v in setup_counts.items()}
    if isinstance(grade_counts, dict):
        payload["grade_counts"] = {str(k): int(v) for k, v in grade_counts.items()}
    payload["net_profit_usdt"] = round(float(result.get("net_profit", 0.0)), 2)
    payload["initial_balance_usdt"] = round(float(result.get("initial_balance", 0.0)), 2)
    return payload


def _artifacts_dir() -> Path:
    root = Path(__file__).resolve().parent.parent.parent / "artifacts"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _load_json_artifact(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            return loaded
    except Exception:
        pass
    return {}


def _update_backtest_result_artifact(result: dict[str, Any], days: int) -> None:
    target = _artifacts_dir() / "backtest_result.json"
    current = _load_json_artifact(target)
    current[str(int(days))] = _backtest_day_window_payload(result)
    target.write_text(json.dumps(current, indent=2), encoding="utf-8")
    result.pop("trade_path_records", None)


def _update_backtest_symbol_artifact(
    result: dict[str, Any],
    days: int,
    *,
    baseline: bool = False,
) -> None:
    """
    Persist symbol-filtered portfolio stats to artifacts/backtest_symbol.json
    (or backtest_symbol_baseline.json when ``baseline=True``).

    Structure: { "7": { "portfolio_symbols": "TAO, RENDER", "RENDER": { ... } } }
    """
    sym_key = str(result.get("symbol", "")).strip()
    if not sym_key:
        return
    filename = "backtest_symbol_baseline.json" if baseline else "backtest_symbol.json"
    target = _artifacts_dir() / filename
    current = _load_json_artifact(target)
    day_key = str(int(days))
    day_block = current.get(day_key)
    if not isinstance(day_block, dict):
        day_block = {}
    portfolio = result.get("portfolio_symbols")
    if portfolio:
        day_block["portfolio_symbols"] = str(portfolio)
    day_block[sym_key] = _backtest_symbol_day_window_payload(result)
    current[day_key] = day_block
    target.write_text(json.dumps(current, indent=2), encoding="utf-8")


def _artifact_result_has_portfolio_window(src: Any) -> bool:
    """True when a backtest_result.json day key holds full portfolio KPIs."""
    return isinstance(src, dict) and "roi_percent" in src


_BASELINE_CONFIG_KEYS: tuple[str, ...] = (
    "INITIAL_CAPITAL",
    "LEVERAGE",
    "RISK_PER_TRADE",
    "MAX_EXECUTION_RISK_PER_TRADE",
    "MAX_OPEN_POSITIONS",
    "MAX_TRADES_PER_DAY",
    "MAX_DAILY_LOSS",
    "MAX_LOSSES_PER_DAY",
    "MIN_POSITION_PCT_OF_BALANCE",
    "MIN_SL_DISTANCE",
    "EXPOSURE_MULTIPLIER",
    "TOTAL_EXPOSURE_MULTIPLIER",
)


def _baseline_config_from_settings() -> dict[str, float | int]:
    """Snapshot risk/sizing knobs from settings (values loaded from .env)."""
    out: dict[str, float | int] = {}
    for key in _BASELINE_CONFIG_KEYS:
        raw = getattr(settings, key, None)
        if isinstance(raw, bool):
            out[key] = int(raw)
        elif isinstance(raw, int) and not isinstance(raw, bool):
            out[key] = int(raw)
        else:
            out[key] = float(raw)
    return out


def _update_metrics_baseline_artifact(*, symbols: list[str]) -> None:
    """
    Sync artifacts/backtest_baseline.json baseline fields from artifacts/backtest_result.json
    by matching metrics[].period_days to backtest_result day keys.

    Copies portfolio KPIs plus per-strategy blocks ``liquidity_reversal`` and ``trend_following``
    when present on the result window (``liquidity_reversal`` omits ``sweep_trades`` for baseline).
    """
    root = Path(__file__).resolve().parent.parent.parent / "artifacts"
    result_path = root / "backtest_result.json"
    baseline_path = root / "backtest_baseline.json"
    if not result_path.exists() or not baseline_path.exists():
        return
    try:
        result_data = json.loads(result_path.read_text(encoding="utf-8"))
        metrics_data = json.loads(baseline_path.read_text(encoding="utf-8"))
    except Exception:
        return
    if not isinstance(result_data, dict) or not isinstance(metrics_data, dict):
        return
    rows = metrics_data.get("metrics")
    if not isinstance(rows, list):
        return

    coin = ",".join(str(s).replace("USDT", "") for s in symbols) if symbols else "TAO"
    changed = False
    config_snapshot = _baseline_config_from_settings()
    if metrics_data.get("config") != config_snapshot:
        metrics_data["config"] = config_snapshot
        changed = True
    fields = (
        "roi_percent",
        "total_trades",
        "trades_per_day",
        "win_rate_percent",
        "profit_factor",
        "max_drawdown_percent",
    )
    # Auto-create missing period rows so --baseline works for new horizons (e.g. 7d).
    # Only full portfolio windows in backtest_result.json count.
    existing_periods: set[int] = set()
    for row in rows:
        if isinstance(row, dict) and row.get("period_days") is not None:
            try:
                existing_periods.add(int(row.get("period_days")))
            except Exception:
                pass
    for key in result_data.keys():
        try:
            p = int(key)
        except Exception:
            continue
        src_candidate = result_data.get(str(p))
        if p not in existing_periods and _artifact_result_has_portfolio_window(src_candidate):
            rows.append({"period_days": p, "baseline": {"coin": coin}})
            existing_periods.add(p)
            changed = True

    for row in rows:
        if not isinstance(row, dict):
            continue
        period = row.get("period_days")
        if period is None:
            continue
        period_key = str(int(period))
        src = result_data.get(period_key)
        if not isinstance(src, dict):
            continue
        if not _artifact_result_has_portfolio_window(src):
            continue
        baseline = row.get("baseline")
        if not isinstance(baseline, dict):
            baseline = {}
            row["baseline"] = baseline
        baseline["coin"] = coin
        for key in fields:
            if key in src:
                baseline[key] = src[key]
                changed = True
        for nested_key in ("liquidity_reversal", "trend_following"):
            nested = src.get(nested_key)
            if isinstance(nested, dict):
                merged = copy.deepcopy(nested)
                if nested_key == "liquidity_reversal":
                    merged.pop("sweep_trades", None)
                baseline[nested_key] = merged
                changed = True

    # Remove coin-only stubs left over from older runs when result has no full window for that period.
    kept: list[Any] = []
    for row in rows:
        if not isinstance(row, dict):
            kept.append(row)
            continue
        period = row.get("period_days")
        if period is None:
            kept.append(row)
            continue
        period_key = str(int(period))
        baseline = row.get("baseline")
        if not isinstance(baseline, dict):
            kept.append(row)
            continue
        if "roi_percent" in baseline or _artifact_result_has_portfolio_window(result_data.get(period_key)):
            kept.append(row)
            continue
        changed = True
    rows[:] = kept

    # Keep artifacts deterministic and easy to scan: shortest period first (e.g. 7, 30, 60, 90).
    rows.sort(
        key=lambda r: (
            int(r.get("period_days")) if isinstance(r, dict) and r.get("period_days") is not None else 10**9
        )
    )

    if changed:
        baseline_path.write_text(json.dumps(metrics_data, indent=2), encoding="utf-8")


def main() -> int:
    os.environ["JOURNAL_OVERWRITE"] = "true"
    parser = argparse.ArgumentParser(description="Run A+ pullback backtest")
    parser.add_argument(
        "--symbol",
        type=str,
        default=None,
        help=(
            "Report filter: RENDER or TAO,RENDER. With multiple SYMBOLS in .env, runs the full "
            "portfolio and prints a detailed report for these symbols only. Use --only to simulate one symbol."
        ),
    )
    parser.add_argument(
        "--symbol-baseline",
        type=str,
        default=None,
        dest="symbol_baseline",
        help=(
            "Like --symbol but writes artifacts/backtest_symbol_baseline.json instead of "
            "backtest_symbol.json (no regular symbol artifact written)."
        ),
    )
    parser.add_argument(
        "--only",
        action="store_true",
        help="Simulate only --symbol (skip full portfolio when SYMBOLS lists multiple coins)",
    )
    parser.add_argument("--days", type=int, default=30, choices=[7, 30, 60, 90], help="Backtest period in days")
    parser.add_argument(
        "--initial",
        type=float,
        default=None,
        help="Starting virtual balance (default: INITIAL_CAPITAL from settings)",
    )
    parser.add_argument(
        "--max-open-positions",
        type=int,
        default=settings.MAX_OPEN_POSITIONS,
        help="Portfolio max concurrent open positions",
    )
    parser.add_argument(
        "--allow-symbol-stacking",
        action="store_true",
        help="Allow opening more than one position per symbol (default: off)",
    )
    parser.add_argument("--all", action="store_true", help="Use predefined allowed symbol list")
    parser.add_argument(
        "--portfolio",
        action="store_true",
        help="Print per-symbol comparison table from combined portfolio run",
    )
    parser.add_argument("--ai", action="store_true", help="Enable AI evaluation before trade execution")
    parser.add_argument("--json", action="store_true", help="Print raw JSON instead of the text report")
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Print detailed report for full portfolio runs (not needed with --symbol filter)",
    )
    parser.add_argument(
        "--baseline",
        action="store_true",
        help=(
            "Update artifacts/backtest_baseline.json from artifacts/backtest_result.json "
            "(portfolio KPIs + liquidity_reversal / trend_following per period_days). "
            "With --symbol, also writes the same symbol window to "
            "artifacts/backtest_symbol_baseline.json"
        ),
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Write verbose backtest lines to logs/<date>.log (default: no file logging)",
    )
    parser.add_argument(
        "--exit-tuning",
        choices=("auto", "on", "off"),
        default="auto",
        help=(
            "Exit tuned thresholds (exit_tuning.py): auto uses APPLY_EXIT_TUNING from .env "
            "like live; on/off override for experiments or CI"
        ),
    )
    parser.add_argument(
        "--daily-stat",
        action="store_true",
        dest="daily_stat",
        help="Upsert each simulated UTC day into data/performance/mm-yyyy_statistics.json (same schema as live snapshots)",
    )
    parser.add_argument(
        "--exit-metrics",
        action="store_true",
        dest="exit_metrics",
        help="Write artifacts/backtest_exit_metrics.json (time exit / SL / TP breakdown; entry/tp1/tp2 time-exit buckets)",
    )
    parser.add_argument(
        "--exit-baseline",
        action="store_true",
        dest="exit_baseline",
        help="Write artifacts/backtest_exit_baseline.json (same schema as --exit-metrics, but does not write exit_metrics)",
    )
    parser.add_argument(
        "--collect",
        action="store_true",
        help="Write position analysis records to data/position_analysis/ (default: skip)",
    )
    parser.add_argument(
        "--fetch",
        nargs="*",
        metavar="SYMBOL",
        default=None,
        help=(
            "Download data/history_data CSVs for listed symbols only (e.g. RENDER), then run backtest. "
            "Bare --fetch fetches all settings.SYMBOLS. Omit --fetch to rely on HISTORY_AUTO_FETCH "
            "(when true, missing ranges are fetched for every symbol in the backtest run)."
        ),
    )
    args = parser.parse_args()

    if args.collect:
        analysis_file = Path(__file__).resolve().parent.parent.parent / "data" / "position_analysis" / "position_analysis_data.json"
        if analysis_file.exists():
            analysis_file.unlink()

    run_started = time.perf_counter()
    portfolio_syms = _portfolio_symbols()
    report_symbols: list[str] | None = None
    symbol_arg = args.symbol or args.symbol_baseline
    if symbol_arg:
        report_symbols = [
            s
            for s in (_normalize_symbol(t) for t in _parse_symbols_arg(symbol_arg))
            if s and s in settings.ALLOWED_SYMBOLS
        ]
        if not report_symbols:
            raise RuntimeError("No valid symbol in --symbol / --symbol-baseline (check ALLOWED_SYMBOLS)")

    run_symbols = _resolve_backtest_run_symbols(
        use_all=bool(args.all),
        portfolio_table=bool(args.portfolio),
        only=bool(args.only),
        symbol_arg=symbol_arg,
        portfolio_syms=portfolio_syms,
        report_symbols=report_symbols,
    )
    if not run_symbols:
        raise RuntimeError("No valid symbol provided. Example: --symbol RENDER or --all")
    symbols = run_symbols
    report_filter_active = bool(
        report_symbols
        and len(report_symbols) < len(run_symbols)
    )
    if report_filter_active:
        run_label = ", ".join(s.replace("USDT", "") for s in run_symbols)
        report_label = ", ".join(s.replace("USDT", "") for s in report_symbols)
        print(
            f"Portfolio run: {run_label} | Report filter: {report_label}",
            flush=True,
        )

    _mode = str(getattr(settings, "MODE", "")).strip().lower() or "unknown"
    _data_source = str(getattr(settings, "DATA_SOURCE", "")).strip().lower() or "unknown"
    print(f"MODE: {_mode} | DATA SOURCE: {_data_source}", flush=True)

    if args.fetch is not None:
        if _mode != "backtest":
            raise RuntimeError("--fetch requires MODE=backtest in .env")
        if not bool(getattr(settings, "HISTORY_AUTO_FETCH", False)):
            raise RuntimeError("--fetch requires HISTORY_AUTO_FETCH=true in .env")
        fetch_syms = _resolve_fetch_symbols(list(args.fetch))
        if not fetch_syms:
            raise RuntimeError("No valid symbols for --fetch (check ALLOWED_SYMBOLS)")
        print(f"Fetching history: {', '.join(s.replace('USDT', '') for s in fetch_syms)}", flush=True)
        counts = prefetch_history_symbols(fetch_syms, days=int(args.days))
        for sym, tf_counts in counts.items():
            short = sym.replace("USDT", "")
            parts = ", ".join(f"{tf}={n}" for tf, n in tf_counts.items())
            print(f"  {short}: {parts}", flush=True)

    exit_tuning_kw: dict[str, bool] = {}
    if args.exit_tuning == "on":
        exit_tuning_kw["apply_exit_tuning"] = True
    elif args.exit_tuning == "off":
        exit_tuning_kw["apply_exit_tuning"] = False

    result = run_portfolio_backtest(
        run_symbols,
        days=args.days,
        initial_balance=args.initial,
        max_open_positions=max(1, int(args.max_open_positions)),
        one_position_per_symbol=not args.allow_symbol_stacking,
        use_ai=args.ai,
        write_daily_stat=bool(args.daily_stat),
        file_log=args.log,
        write_collect=bool(args.collect),
        **exit_tuning_kw,
    )
    portfolio_result = result
    if report_filter_active and report_symbols:
        result = _filter_result_for_report(result, report_symbols)
    if bool(getattr(args, "exit_metrics", False)):
        _write_backtest_exit_metrics_artifact(result, sim_days=int(args.days))
    elif bool(getattr(args, "exit_baseline", False)):
        _write_backtest_exit_baseline_artifact(result, sim_days=int(args.days))
    if report_filter_active and report_symbols:
        if args.symbol_baseline:
            _update_backtest_symbol_artifact(result, int(args.days), baseline=True)
        else:
            _update_backtest_symbol_artifact(result, int(args.days))
            if args.baseline:
                _update_backtest_symbol_artifact(result, int(args.days), baseline=True)
        _update_backtest_result_artifact(portfolio_result, int(args.days))
    else:
        _update_backtest_result_artifact(result, int(args.days))
    if args.baseline:
        _update_metrics_baseline_artifact(symbols=symbols)
    if args.portfolio:
        rows: list[dict[str, Any]] = []
        per_symbol_stats = result.get("per_symbol")
        if not isinstance(per_symbol_stats, dict):
            per_symbol_stats = {}
        table_symbols = list(per_symbol_stats.keys())
        total_initial_capital = float(result.get("initial_balance", 0.0))
        initial_capital_per_symbol = (
            total_initial_capital / float(len(run_symbols)) if run_symbols else 0.0
        )
        for sym in table_symbols:
            stats = per_symbol_stats.get(sym, {}) if isinstance(per_symbol_stats.get(sym, {}), dict) else {}
            capital = float(stats.get("capital", 0.0))
            pnl = float(stats.get("net_profit", 0.0))
            roi = float(stats.get("roi", (pnl / capital * 100.0) if capital != 0.0 else 0.0))
            rows.append(
                {
                    "symbol": sym,
                    "trades": int(stats.get("trades", 0)),
                    "roi": roi,
                    "win_rate": float(stats.get("win_rate", 0.0)) * 100.0,
                    "profit_factor": stats.get("profit_factor"),
                    "max_drawdown": float(stats.get("max_drawdown", 0.0)) * 100.0,
                    "pnl": pnl,
                    "initial_capital": initial_capital_per_symbol,
                    "capital": capital,
                    "avg_alloc": float(stats.get("avg_alloc", 0.0)),
                }
            )
        total_capital = float(max((float(row.get("capital", 0.0)) for row in rows), default=0.0))
        total_pnl = float(sum(float(row.get("pnl", 0.0)) for row in rows))
        total_trades = int(sum(int(row.get("trades", 0)) for row in rows))
        total_alloc_sum = float(
            sum(float(row.get("avg_alloc", 0.0)) * float(int(row.get("trades", 0))) for row in rows)
        )
        total_avg_alloc = (total_alloc_sum / float(total_trades)) if total_trades > 0 else 0.0
        total = {
            "trades": total_trades,
            "roi": (total_pnl / total_initial_capital * 100.0) if total_initial_capital != 0.0 else 0.0,
            "win_rate": float(result.get("win_rate", 0.0)) * 100.0,
            "profit_factor": result.get("profit_factor"),
            "max_drawdown": float(result.get("max_drawdown", 0.0)) * 100.0,
            "pnl": total_pnl,
            "initial_capital": total_initial_capital,
            "capital": total_capital,
            "avg_alloc": total_avg_alloc,
        }
        print(format_compare_table(rows, total))
    elif args.json:
        payload = {
            k: v
            for k, v in result.items()
            if k not in ("report", "trade_path_records")
        }
        print(json.dumps(payload, indent=2))
    elif args.detailed or report_filter_active:
        symbol_filtered = bool(result.get("portfolio_symbols")) and len(
            result.get("per_symbol") or {}
        ) <= 1
        if not symbol_filtered:
            note = result.get("report_note")
            if note:
                print(str(note))
        print(result.get("report", format_backtest_report(result)))
        if not symbol_filtered:
            per_symbol = result.get("per_symbol")
            if isinstance(per_symbol, dict):
                print()
                print("Per-symbol breakdown:")
                for sym, stats in per_symbol.items():
                    pf = stats.get("profit_factor")
                    pf_str = "n/a" if pf is None else f"{float(pf):.2f}"
                    trades = int(stats.get("trades", 0))
                    win_rate = float(stats.get("win_rate", 0.0)) * 100.0
                    net = float(stats.get("net_profit", 0.0))
                    tpd = trades / max(float(args.days), 1.0)
                    print(
                        f"- {sym.replace('USDT', '')}: net={net:+.2f}, trades={trades}, "
                        f"win={win_rate:.2f}%, pf={pf_str}, trades/day={tpd:.2f}"
                    )
    else:
        note = result.get("report_note")
        if note:
            print(str(note))
        print(format_portfolio_summary(result))
    elapsed_sec = int(time.perf_counter() - run_started)
    _running_time_line = f"Running Time: {elapsed_sec // 60}:{elapsed_sec % 60:02d}"
    if args.json:
        print(_running_time_line, file=sys.stderr)
    else:
        print(_running_time_line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
