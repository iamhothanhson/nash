"""
Elite Dynamic Stop Loss Engine — multi-layer trailing stop.

Exit sizing / TP ladders are unchanged elsewhere; this module only computes stop price.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from indicators import calculate_adx, calculate_atr

TrendStrength = Literal["weak", "normal", "strong"]


@dataclass(frozen=True)
class MarketSnapshot:
    current_price: float
    atr: float
    highs: tuple[float, ...]
    lows: tuple[float, ...]
    trend_strength: TrendStrength
    atr_relative: float  # atr / price


def structure_lookback(atr_relative: float) -> int:
    if atr_relative < 0.003:
        return 3
    if atr_relative < 0.008:
        return 5
    return 8


def classify_high_volatility(atr_relative: float) -> bool:
    return atr_relative >= 0.008


def atr_multiplier(*, trend_strength: TrendStrength, high_volatility: bool) -> float:
    if high_volatility:
        return 2.2
    if trend_strength == "strong":
        return 2.0
    return 1.5


def trend_strength_from_adx(adx: float) -> TrendStrength:
    if adx >= 28.0:
        return "strong"
    if adx >= 18.0:
        return "normal"
    return "weak"


def mfe_lock_fraction(roi_percent: float) -> float | None:
    """ROI is leveraged margin ROI % (same units as _position_roi_percent)."""
    if roi_percent < 0.5:
        return None
    if roi_percent < 1.5:
        return 0.20
    if roi_percent < 3.0:
        return 0.50
    return 0.80


def _structure_sl_price(
    *,
    is_long: bool,
    highs: tuple[float, ...],
    lows: tuple[float, ...],
    lookback: int,
) -> float | None:
    if lookback <= 0:
        return None
    hi = highs[-lookback:] if len(highs) >= lookback else highs
    lo = lows[-lookback:] if len(lows) >= lookback else lows
    if not hi or not lo:
        return None
    if is_long:
        return float(min(lo))
    return float(max(hi))


def _atr_sl_price(
    *,
    is_long: bool,
    current_price: float,
    atr: float,
    k: float,
) -> float:
    if is_long:
        return float(current_price) - k * float(atr)
    return float(current_price) + k * float(atr)


def _mfe_sl_price(
    *,
    is_long: bool,
    entry: float,
    peak_price: float,
    lock_frac: float,
) -> float:
    if is_long:
        return float(entry) + lock_frac * (float(peak_price) - float(entry))
    return float(entry) - lock_frac * (float(entry) - float(peak_price))


def compute_dynamic_sl(
    *,
    entry_price: float,
    is_long: bool,
    initial_sl: float,
    max_favorable_price: float,
    current_roi_percent: float,
    market: MarketSnapshot,
) -> float:
    """
    Combine invalidation, structure, ATR, and optional MFE lock into one stop price.

    Long  → final_sl = max(candidates) — highest stop = tightest trail (never below initial_sl).
    Short → final_sl = min(candidates) — lowest stop among shorts = tightest trail (never above initial_sl).
    """
    px = float(market.current_price)
    atr = max(float(market.atr), 1e-12)
    atr_rel = float(market.atr_relative)
    lb = structure_lookback(atr_rel)
    high_vol = classify_high_volatility(atr_rel)
    k = atr_multiplier(trend_strength=market.trend_strength, high_volatility=high_vol)

    inv = float(initial_sl)
    struct = _structure_sl_price(
        is_long=is_long,
        highs=market.highs,
        lows=market.lows,
        lookback=lb,
    )
    atr_sl = _atr_sl_price(is_long=is_long, current_price=px, atr=atr, k=k)

    lock = mfe_lock_fraction(float(current_roi_percent))
    candidates: list[float] = [inv, atr_sl]
    if struct is not None:
        candidates.append(struct)

    peak = float(max_favorable_price)
    if lock is not None:
        mfe_sl = _mfe_sl_price(is_long=is_long, entry=entry_price, peak_price=peak, lock_frac=lock)
        candidates.append(mfe_sl)

    if is_long:
        # Never loosen invalidation: stop cannot move below initial_sl.
        return max(candidates)
    # Short: never loosen below risk — stop cannot move below initial_sl for short... short SL is above entry.
    # "Never loosen" for short means do not move SL further from entry (widen). Higher SL price = wider risk for short.
    # So final_sl must be <= initial_sl for short (stay at least as tight as initial).
    return min(candidates)


def update_max_favorable_price(
    *,
    is_long: bool,
    prior_peak: float,
    bar_high: float,
    bar_low: float,
) -> float:
    if is_long:
        return max(float(prior_peak), float(bar_high))
    return min(float(prior_peak), float(bar_low))


def build_market_snapshot(
    *,
    current_price: float,
    atr: float,
    highs: list[float],
    lows: list[float],
    adx: float,
) -> MarketSnapshot:
    px = max(float(current_price), 1e-12)
    atr_rel = float(atr) / px
    return MarketSnapshot(
        current_price=float(current_price),
        atr=float(atr),
        highs=tuple(highs),
        lows=tuple(lows),
        trend_strength=trend_strength_from_adx(float(adx)),
        atr_relative=atr_rel,
    )


def sync_dynamic_stop_for_bar(
    pos: Any,
    *,
    df5: pd.DataFrame,
    df15: pd.DataFrame,
    high: float,
    low: float,
    close_px: float,
    current_roi_percent: float,
    atr_period: int = 14,
    adx_period: int = 14,
    swing_history_bars: int = 64,
) -> None:
    """Update `max_favorable_price` and `current_stop_loss` on `pos` (duck-typed position row)."""
    is_long = str(getattr(pos, "direction", "")).upper() == "LONG"
    entry = float(getattr(pos, "entry", 0.0))
    if getattr(pos, "initial_sl", 0.0) <= 0:
        setattr(pos, "initial_sl", float(getattr(pos, "stop_loss", entry)))
    peak = float(getattr(pos, "max_favorable_price", 0.0))
    if peak <= 0:
        peak = entry
    peak = update_max_favorable_price(is_long=is_long, prior_peak=peak, bar_high=float(high), bar_low=float(low))
    setattr(pos, "max_favorable_price", peak)

    tail = min(len(df5), swing_history_bars)
    window = df5.tail(tail) if len(df5) else df5
    highs = [float(x) for x in window["high"].tolist()] if len(window) else [float(high)]
    lows = [float(x) for x in window["low"].tolist()] if len(window) else [float(low)]

    d15 = df15.tail(120) if len(df15) >= 20 else df15
    atr_series = calculate_atr(window.reset_index(drop=True), atr_period) if len(window) >= atr_period + 1 else None
    atr_v = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) else float(high - low)
    adx_series = calculate_adx(d15.reset_index(drop=False), adx_period) if len(d15) >= 20 else None
    adx_v = float(adx_series.iloc[-1]) if adx_series is not None and len(adx_series) else 22.0

    mkt = build_market_snapshot(
        current_price=float(close_px),
        atr=atr_v,
        highs=highs,
        lows=lows,
        adx=adx_v,
    )
    initial_sl = float(getattr(pos, "initial_sl"))
    final_sl = compute_dynamic_sl(
        entry_price=entry,
        is_long=is_long,
        initial_sl=initial_sl,
        max_favorable_price=peak,
        current_roi_percent=float(current_roi_percent),
        market=mkt,
    )
    setattr(pos, "last_roi_percent", float(current_roi_percent))
    setattr(pos, "current_stop_loss", float(final_sl))
