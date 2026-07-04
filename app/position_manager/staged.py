from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from common.rounding import format_price, round_qty
from coins.loader import price_rounding_decimal
from config import settings
from execution.exchange_tp_orders import exchange_tp_detect_by_order_status_enabled
from indicators import calculate_atr
from monitoring.logger import log
from position_management.post_tp1_stop import (
    apply_post_tp1_stop_on_first_hit,
    compute_post_tp1_stop_price,
)
from position_management.tp3_structure_trail import (
    apply_tp3_structure_trail,
    is_new_15m_close,
    is_runner_tp3,
    runner_floor_stop,
)


@dataclass
class ManagedPosition:
    symbol: str
    direction: str  # LONG | SHORT
    qty_total: float
    qty_open: float
    entry: float
    stop_loss: float
    tp1: float
    tp2: float
    tp3: float
    setup_type: str = "unknown"
    setup_grade: str = "A+"
    # Backtest / attribution: "liquidity" | "trend" (from liquidity sweep vs trend-following signal).
    strategy_family: str = "liquidity"
    open_time_iso: str = ""
    initial_risk_usd: float = 0.0
    # Full-position planned max loss (USDT); 0 => derive from initial_risk_usd in hard_stop.max_loss_allowed.
    max_hard_stop_loss_usd: float = 0.0
    # Live/demo: after a failed exchange close during HARD STOP, block re-fire until this unix time.
    hard_stop_retry_after_ts: float = 0.0
    exit_via_hard_stop: bool = False
    close_journal_logged: bool = False
    market_structure: str = "Range"
    market_regime_detail: dict | None = None
    tp1_close_frac: float = 0.50
    tp2_close_frac: float = 0.30
    hit_tp1: bool = False
    hit_tp2: bool = False
    hit_tp3: bool = False
    closed: bool = False
    current_stop_loss: float = 0.0
    realized_pnl: float = 0.0
    # Exchange SL sync (live/demo): last values successfully placed; order id for cancel/replace.
    last_sent_stop_loss: float = 0.0
    last_sent_qty_open: float = 0.0
    stop_exchange_order_id: int | None = None
    exchange_tp_orders_placed: bool = False
    exchange_tp1_order_id: int | None = None
    exchange_tp2_order_id: int | None = None
    # "take_profit_market" — conditional TAKE_PROFIT_MARKET algo order.
    exchange_tp2_order_kind: str = ""
    # Stop sync race guards:
    # - epoch increments on each intent to replace stop,
    # - inflight-until prevents overlapping cancel/replace bursts.
    stop_sync_epoch: int = 0
    stop_sync_inflight_until_ts: float = 0.0
    roi_history: list[dict[str, float]] = field(default_factory=list)
    max_roi_seen: float = 0.0
    tp1_hit_at_ts: float | None = None
    tp2_hit_at_ts: float | None = None
    # Live/demo: max ``userTrades.time`` (ms) already attributed to a partial TP leg.
    last_exchange_trade_ms: int = 0
    # TP3 runner (15m structure trail) — active when tp3 <= 0 after TP2.
    tp3_trailing_stop: float = 0.0
    tp3_confirmed_swing: float = 0.0
    tp3_next_swing_trigger: float = 0.0
    tp3_trend_structure: str = "pending"
    tp3_estimated_runner_pct: float = 0.0
    last_15m_bar_ts: float = 0.0

    def __post_init__(self) -> None:
        if self.current_stop_loss <= 0:
            self.current_stop_loss = float(self.stop_loss)


@dataclass(frozen=True)
class ExitFill:
    tag: str  # SL HIT | TP1 HIT | TP2 HIT | TP3 HIT | CLOSE
    price: float
    qty_closed: float
    qty_remaining: float
    pnl: float


def _is_long(pos: ManagedPosition) -> bool:
    return str(pos.direction).upper() == "LONG"


def atr_from_df5(
    df5: pd.DataFrame,
    *,
    period: int | None = None,
    fallback_range: float | None = None,
) -> float | None:
    """Latest 5m ATR for TP2 runner trail; ``None`` when history is too short."""
    if df5 is None or len(df5) < 2:
        return None
    p = int(period if period is not None else getattr(settings, "TP2_RUNNER_ATR_PERIOD", 14))
    try:
        window = df5.tail(max(p + 2, 32))
        series = calculate_atr(window.reset_index(drop=True), p)
        if series is not None and len(series):
            v = float(series.iloc[-1])
            if v > 0:
                return v
    except Exception:
        pass
    if fallback_range is not None and float(fallback_range) > 0:
        return float(fallback_range)
    try:
        last = df5.iloc[-1]
        return max(float(last["high"]) - float(last["low"]), 1e-12)
    except Exception:
        return None


def log_tp1_breakeven_memory(pos: ManagedPosition, *, qty_remaining: float) -> None:
    """Daily log for TP1 → breakeven SL at entry (call after ``[TP1 HIT]`` line)."""
    pd = price_rounding_decimal(pos.symbol)
    sl_px = compute_post_tp1_stop_price(float(pos.entry), pos.direction, symbol=pos.symbol)
    log(
        f"[BREAKEVEN] {pos.symbol} | Set SL to entry after TP1 Hit | "
        f"entry={format_price(float(pos.entry), pd)} | "
        f"sl={format_price(sl_px, pd)} | "
        f"qty_remaining={round_qty(float(qty_remaining), 3):.3f}"
    )


def tp1_on_exchange(pos: ManagedPosition) -> bool:
    """True when a TP1 reduce-only limit was placed on the exchange for this leg."""
    return getattr(pos, "exchange_tp1_order_id", None) is not None


def tp2_on_exchange(pos: ManagedPosition) -> bool:
    """True when a TP2 reduce-only limit was placed on the exchange for this leg."""
    return getattr(pos, "exchange_tp2_order_id", None) is not None


def detect_hits(pos: ManagedPosition, *, high: float, low: float) -> dict[str, bool]:
    sl = float(pos.current_stop_loss)
    if pos.hit_tp2 and is_runner_tp3(pos.tp3):
        sl = runner_floor_stop(pos)
    if _is_long(pos):
        return {
            "sl_hit": low <= sl,
            "tp1_hit": high >= float(pos.tp1),
            "tp2_hit": high >= float(pos.tp2),
        }
    return {
        "sl_hit": high >= sl,
        "tp1_hit": low <= float(pos.tp1),
        "tp2_hit": low <= float(pos.tp2),
    }


def _init_runner_trail(
    pos: ManagedPosition,
    *,
    df15: pd.DataFrame | None,
    bar_ts: float | None,
) -> None:
    """Seed TP3 structure trail immediately after TP2 partial."""
    if df15 is None or len(df15) < 8:
        return
    ts = float(bar_ts) if bar_ts is not None else float(getattr(pos, "last_15m_bar_ts", 0.0) or 0.0)
    apply_tp3_structure_trail(
        pos,
        df15,
        bar_ts=ts,
        floor_stop=runner_floor_stop(pos),
    )


def _maybe_runner_exit_on_15m(
    pos: ManagedPosition,
    *,
    df15: pd.DataFrame | None,
    bar_ts: float | None,
    pnl_fn: Any,
) -> list[ExitFill]:
    """Evaluate TP3 runner exit on each new closed 15m bar."""
    if not pos.hit_tp2 or pos.qty_open <= 0 or not is_runner_tp3(pos.tp3):
        return []
    if df15 is None or len(df15) < 8 or bar_ts is None:
        return []
    if not is_new_15m_close(bar_ts=float(bar_ts), last_processed_ts=float(pos.last_15m_bar_ts)):
        return []

    last_close = float(df15["close"].iloc[-1])
    prior_trail = float(getattr(pos, "tp3_trailing_stop", 0.0) or 0.0)
    is_long = _is_long(pos)

    snap = apply_tp3_structure_trail(
        pos,
        df15,
        bar_ts=float(bar_ts),
        floor_stop=runner_floor_stop(pos),
    )
    should_exit = False
    crossed_prior_trail = False
    if prior_trail > 0.0:
        crossed_prior_trail = (last_close < prior_trail) if is_long else (last_close > prior_trail)
        should_exit = crossed_prior_trail
    if not should_exit and snap.trend_structure == "broken":
        should_exit = True

    if not should_exit:
        return []

    if crossed_prior_trail and prior_trail > 0.0:
        exit_px = float(prior_trail)
    else:
        exit_px = float(last_close)
    qty = float(pos.qty_open)
    pnl = float(pnl_fn(pos.direction, pos.entry, exit_px, qty))
    pos.realized_pnl += pnl
    pos.qty_open = 0.0
    pos.hit_tp3 = True
    pos.closed = True
    return [
        ExitFill("TP3 HIT", exit_px, qty, pos.qty_open, pnl),
        ExitFill("CLOSE", exit_px, qty, pos.qty_open, pos.realized_pnl),
    ]


def _sub_bar_touch_ts(
    touch_px: float,
    *,
    is_long: bool,
    sub_bars_1m: pd.DataFrame,
    fallback: float,
) -> float:
    """Find the first 1m sub-bar where price touched touch_px, estimate the timestamp."""
    ts_col = pd.to_datetime(sub_bars_1m["timestamp"], utc=True)
    for idx in range(len(sub_bars_1m)):
        row = sub_bars_1m.iloc[idx]
        row_high = float(row["high"])
        row_low = float(row["low"])
        if is_long:
            if row_high >= touch_px:
                row_open = float(row["open"])
                row_ts = float(ts_col.iloc[idx].timestamp())
                if row_high > row_open:
                    frac = (touch_px - row_open) / (row_high - row_open)
                else:
                    frac = 0.0
                return row_ts + max(0.0, min(60.0, frac * 60.0))
        else:
            if row_low <= touch_px:
                row_open = float(row["open"])
                row_ts = float(ts_col.iloc[idx].timestamp())
                if row_low < row_open:
                    frac = (row_open - touch_px) / (row_open - row_low)
                else:
                    frac = 0.0
                return row_ts + max(0.0, min(60.0, frac * 60.0))
    return fallback


def _touch_ts_for_tp(
    pos: ManagedPosition,
    touch_px: float,
    *,
    now_ts: float | None,
    sub_bars_1m: pd.DataFrame | None,
    fallback: float | None,
) -> float:
    if sub_bars_1m is not None and len(sub_bars_1m):
        return _sub_bar_touch_ts(
            touch_px,
            is_long=_is_long(pos),
            sub_bars_1m=sub_bars_1m,
            fallback=float(now_ts) if now_ts is not None else float(fallback or 0.0),
        )
    return float(now_ts) if now_ts is not None else float(fallback or 0.0)


def apply_staged_management(
    pos: ManagedPosition,
    *,
    high: float,
    low: float,
    now_ts: float | None = None,
    pnl_fn: Any,
    mark_price: float | None = None,
    atr: float | None = None,
    df15: pd.DataFrame | None = None,
    sub_bars_1m: pd.DataFrame | None = None,
) -> list[ExitFill]:
    """
    Apply one-candle staged exits with deterministic priority:
    1) SL, 2) TP3 runner (15m structure on close), 3) TP1, 4) TP2.
    """
    _ = mark_price
    _ = atr
    if pos.closed or pos.qty_open <= 0:
        pos.closed = True
        pos.qty_open = 0.0
        return []

    runner_fills = _maybe_runner_exit_on_15m(pos, df15=df15, bar_ts=now_ts, pnl_fn=pnl_fn)
    if runner_fills:
        return runner_fills

    out: list[ExitFill] = []
    hits = detect_hits(pos, high=high, low=low)

    # Priority 1: stop first (conservative intrabar assumption).
    if hits["sl_hit"]:
        from position_management.stop_exchange_sync import exchange_stop_is_active

        if not exchange_stop_is_active(pos):
            qty = float(pos.qty_open)
            px = float(pos.current_stop_loss)
            pnl = float(pnl_fn(pos.direction, pos.entry, px, qty))
            pos.realized_pnl += pnl
            pos.qty_open = 0.0
            pos.closed = True
            if pos.hit_tp2 and is_runner_tp3(pos.tp3):
                pos.hit_tp3 = True
            out.append(ExitFill("SL HIT", px, qty, pos.qty_open, pnl))
            out.append(ExitFill("CLOSE", px, qty, pos.qty_open, pos.realized_pnl))
            return out

    # Legacy fixed TP3 (non-runner positions only).
    if not is_runner_tp3(pos.tp3) and pos.qty_open > 0:
        fixed_tp3 = (_is_long(pos) and high >= float(pos.tp3)) or (
            (not _is_long(pos)) and low <= float(pos.tp3)
        )
        if fixed_tp3:
            qty = float(pos.qty_open)
            px = float(pos.tp3)
            pnl = float(pnl_fn(pos.direction, pos.entry, px, qty))
            pos.realized_pnl += pnl
            pos.qty_open = 0.0
            pos.hit_tp3 = True
            pos.closed = True
            out.append(ExitFill("TP3 HIT", px, qty, pos.qty_open, pnl))
            out.append(ExitFill("CLOSE", px, qty, pos.qty_open, pos.realized_pnl))
            return out

    # Priority 3: TP1 partial (before TP2 when both tag same bar).
    if hits["tp1_hit"] and (not pos.hit_tp1) and pos.qty_open > 0:
        if tp1_on_exchange(pos) and exchange_tp_detect_by_order_status_enabled():
            pass
        elif tp1_on_exchange(pos):
            px = float(pos.tp1)
            qty_before = float(pos.qty_open)
            target_tp1 = float(pos.qty_total) * float(pos.tp1_close_frac)
            runner_after_tp1 = max(0.0, float(pos.qty_total) - target_tp1)
            if qty_before <= runner_after_tp1 + 1e-9:
                # Exchange limit already reduced size (reconcile synced partial).
                leg = max(0.0, float(pos.qty_total) - qty_before)
                rem = qty_before
            else:
                leg = min(target_tp1, qty_before)
                rem = max(0.0, qty_before - leg)
            pnl = float(pnl_fn(pos.direction, pos.entry, px, leg))
            pos.realized_pnl += pnl
            pos.tp1_hit_at_ts = _touch_ts_for_tp(
                pos, float(pos.tp1), now_ts=now_ts, sub_bars_1m=sub_bars_1m,
                fallback=pos.tp1_hit_at_ts,
            )
            apply_post_tp1_stop_on_first_hit(pos)
            out.append(ExitFill("TP1 HIT", px, leg, rem, pnl))
        elif not tp1_on_exchange(pos):
            px = float(pos.tp1)
            qty = min(float(pos.qty_total) * float(pos.tp1_close_frac), float(pos.qty_open))
            pnl = float(pnl_fn(pos.direction, pos.entry, px, qty))
            pos.realized_pnl += pnl
            pos.qty_open = max(0.0, float(pos.qty_open) - qty)
            pos.tp1_hit_at_ts = _touch_ts_for_tp(
                pos, float(pos.tp1), now_ts=now_ts, sub_bars_1m=sub_bars_1m,
                fallback=pos.tp1_hit_at_ts,
            )
            apply_post_tp1_stop_on_first_hit(pos)
            out.append(ExitFill("TP1 HIT", px, qty, pos.qty_open, pnl))
            if pos.qty_open <= 1e-12:
                pos.qty_open = 0.0
                pos.closed = True
                out.append(ExitFill("CLOSE", px, qty, pos.qty_open, pos.realized_pnl))
                return out

    # Priority 4: TP2 partial.
    if hits["tp2_hit"] and (not pos.hit_tp2) and pos.qty_open > 0:
        if tp2_on_exchange(pos) and exchange_tp_detect_by_order_status_enabled():
            pass
        elif tp2_on_exchange(pos):
            px = float(pos.tp2)
            qty_before = float(pos.qty_open)
            target_tp2 = float(pos.qty_total) * float(pos.tp2_close_frac)
            if qty_before <= target_tp2 + 1e-9:
                leg = max(0.0, float(pos.qty_total) - qty_before)
                rem = qty_before
            else:
                leg = min(target_tp2, qty_before)
                rem = max(0.0, qty_before - leg)
            pnl = float(pnl_fn(pos.direction, pos.entry, px, leg))
            pos.realized_pnl += pnl
            pos.hit_tp2 = True
            pos.tp2_hit_at_ts = _touch_ts_for_tp(
                pos, float(pos.tp2), now_ts=now_ts, sub_bars_1m=sub_bars_1m,
                fallback=pos.tp2_hit_at_ts,
            )
            if is_runner_tp3(pos.tp3):
                _init_runner_trail(pos, df15=df15, bar_ts=now_ts)
            out.append(ExitFill("TP2 HIT", px, leg, rem, pnl))
        elif not tp2_on_exchange(pos):
            px = float(pos.tp2)
            qty = min(float(pos.qty_total) * float(pos.tp2_close_frac), float(pos.qty_open))
            pnl = float(pnl_fn(pos.direction, pos.entry, px, qty))
            pos.realized_pnl += pnl
            pos.qty_open = max(0.0, float(pos.qty_open) - qty)
            pos.hit_tp2 = True
            pos.tp2_hit_at_ts = _touch_ts_for_tp(
                pos, float(pos.tp2), now_ts=now_ts, sub_bars_1m=sub_bars_1m,
                fallback=pos.tp2_hit_at_ts,
            )
            if is_runner_tp3(pos.tp3):
                _init_runner_trail(pos, df15=df15, bar_ts=now_ts)
            out.append(ExitFill("TP2 HIT", px, qty, pos.qty_open, pnl))
            if pos.qty_open <= 1e-12:
                pos.qty_open = 0.0
                pos.closed = True
                out.append(ExitFill("CLOSE", px, qty, pos.qty_open, pos.realized_pnl))

    return out
