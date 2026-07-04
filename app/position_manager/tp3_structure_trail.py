"""TP3 runner: 15m market-structure trailing stop (no fixed TP3 target)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import pandas as pd

from config import settings
from indicators import calculate_atr

TrendStructure = Literal["bullish_intact", "bearish_intact", "broken", "pending"]


@dataclass(frozen=True)
class TP3StructureSnapshot:
    trailing_stop: float
    confirmed_swing: float
    next_swing_trigger: float
    trend_structure: TrendStructure
    structure_intact: bool
    exit_on_close: bool
    estimated_runner_pct: float


def is_runner_tp3(tp3: float) -> bool:
    """True when TP3 is the open-ended structure runner (not a fixed price)."""
    return float(tp3) <= 0.0


def fifteen_min_bucket(ts: float) -> int:
    return int(float(ts)) // 900


def is_new_15m_close(*, bar_ts: float, last_processed_ts: float) -> bool:
    """True when ``bar_ts`` belongs to a newer 15m bucket than ``last_processed_ts``."""
    bucket = fifteen_min_bucket(bar_ts)
    if last_processed_ts <= 0.0:
        return bucket > 0
    return bucket > fifteen_min_bucket(last_processed_ts)


def _pivot_indices(values: list[float], *, left: int, right: int, mode: str) -> list[tuple[int, float]]:
    out: list[tuple[int, float]] = []
    n = len(values)
    for i in range(left, n - right):
        window = values[i - left : i + right + 1]
        v = float(values[i])
        if mode == "low" and v == min(window):
            out.append((i, v))
        elif mode == "high" and v == max(window):
            out.append((i, v))
    return out


def _atr_period() -> int:
    return max(1, int(getattr(settings, "TP3_STRUCTURE_TRAIL_ATR_PERIOD", 14)))


def _atr_multiplier() -> float:
    return max(0.01, float(getattr(settings, "TP3_STRUCTURE_TRAIL_ATR_MULTIPLIER", 0.20)))


def _pivot_bars() -> int:
    return max(1, int(getattr(settings, "TP3_STRUCTURE_PIVOT_BARS", 2)))


def _lookback_bars() -> int:
    return max(24, int(getattr(settings, "TP3_STRUCTURE_LOOKBACK_15M", 96)))


def _confirmed_higher_lows(pivot_lows: list[tuple[int, float]]) -> list[tuple[int, float]]:
    if not pivot_lows:
        return []
    chain: list[tuple[int, float]] = [pivot_lows[0]]
    for idx, px in pivot_lows[1:]:
        if px > chain[-1][1]:
            chain.append((idx, px))
        elif px == chain[-1][1]:
            chain[-1] = (idx, px)
    return chain


def _confirmed_lower_highs(pivot_highs: list[tuple[int, float]]) -> list[tuple[int, float]]:
    if not pivot_highs:
        return []
    chain: list[tuple[int, float]] = [pivot_highs[0]]
    for idx, px in pivot_highs[1:]:
        if px < chain[-1][1]:
            chain.append((idx, px))
        elif px == chain[-1][1]:
            chain[-1] = (idx, px)
    return chain


def _next_hl_trigger(lows: list[float], *, confirmed_hl: float) -> float:
    """Price zone for the next higher-low update (recent pullback low above current HL)."""
    if not lows:
        return float(confirmed_hl)
    recent = lows[-8:]
    above = [v for v in recent if v > float(confirmed_hl)]
    if above:
        return float(min(above))
    return float(confirmed_hl)


def _next_lh_trigger(highs: list[float], *, confirmed_lh: float) -> float:
    if not highs:
        return float(confirmed_lh)
    recent = highs[-8:]
    below = [v for v in recent if v < float(confirmed_lh)]
    if below:
        return float(max(below))
    return float(confirmed_lh)


def analyze_tp3_structure(
    df15: pd.DataFrame,
    *,
    direction: str,
    entry: float,
    floor_stop: float,
) -> TP3StructureSnapshot:
    """
    Derive trailing stop from 15m confirmed swing structure and ATR volatility.

    LONG: trail below latest confirmed higher low.
    SHORT: trail above latest confirmed lower high.
    """
    is_long = str(direction).upper() == "LONG"
    atr_period = _atr_period()
    atr_mult = _atr_multiplier()
    pivot = _pivot_bars()
    lookback = _lookback_bars()

    empty = TP3StructureSnapshot(
        trailing_stop=float(floor_stop),
        confirmed_swing=0.0,
        next_swing_trigger=0.0,
        trend_structure="pending",
        structure_intact=True,
        exit_on_close=False,
        estimated_runner_pct=0.0,
    )
    if df15 is None or len(df15) < max(atr_period + 1, pivot * 2 + 3):
        return empty

    window = df15.tail(lookback).reset_index(drop=True)
    lows = [float(x) for x in window["low"].tolist()]
    highs = [float(x) for x in window["high"].tolist()]
    closes = [float(x) for x in window["close"].tolist()]
    last_close = closes[-1] if closes else float(entry)

    atr_series = calculate_atr(df15.tail(lookback + atr_period), atr_period)
    atr15 = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) > 0 else 0.0

    pivot_lows = _pivot_indices(lows, left=pivot, right=pivot, mode="low")
    pivot_highs = _pivot_indices(highs, left=pivot, right=pivot, mode="high")

    def _atr_buffer(swing_price: float) -> float:
        return max(atr_mult * atr15, swing_price * 0.0005)

    if is_long:
        hl_chain = _confirmed_higher_lows(pivot_lows)
        if not hl_chain:
            fallback = float(min(lows[-max(3, pivot + 1) :]))
            buf = _atr_buffer(fallback)
            trail = fallback - buf
            trail = max(float(floor_stop), trail)
            est = max(0.0, (float(max(highs[-12:])) - last_close) / max(last_close, 1e-12) * 100.0)
            return TP3StructureSnapshot(
                trailing_stop=trail,
                confirmed_swing=fallback,
                next_swing_trigger=_next_hl_trigger(lows, confirmed_hl=fallback),
                trend_structure="bullish_intact",
                structure_intact=True,
                exit_on_close=last_close < trail,
                estimated_runner_pct=est,
            )

        confirmed_hl = float(hl_chain[-1][1])
        buf = _atr_buffer(confirmed_hl)
        trail = confirmed_hl - buf
        trail = max(float(floor_stop), trail)

        structure_intact = True
        hl_idx = hl_chain[-1][0]
        for idx, px in pivot_lows:
            if idx > hl_idx and float(px) < confirmed_hl - buf * 0.5:
                structure_intact = False
                break

        est_high = float(max(highs[-12:])) if highs else last_close
        est = max(0.0, (est_high - last_close) / max(last_close, 1e-12) * 100.0)
        return TP3StructureSnapshot(
            trailing_stop=trail,
            confirmed_swing=confirmed_hl,
            next_swing_trigger=_next_hl_trigger(lows, confirmed_hl=confirmed_hl),
            trend_structure="broken" if not structure_intact else "bullish_intact",
            structure_intact=structure_intact,
            exit_on_close=bool(last_close < trail or not structure_intact),
            estimated_runner_pct=est,
        )

    lh_chain = _confirmed_lower_highs(pivot_highs)
    if not lh_chain:
        fallback = float(max(highs[-max(3, pivot + 1) :]))
        buf = _atr_buffer(fallback)
        trail = fallback + buf
        trail = min(float(floor_stop), trail) if float(floor_stop) > 0 else trail
        est = max(0.0, (last_close - float(min(lows[-12:]))) / max(last_close, 1e-12) * 100.0)
        return TP3StructureSnapshot(
            trailing_stop=trail,
            confirmed_swing=fallback,
            next_swing_trigger=_next_lh_trigger(highs, confirmed_lh=fallback),
            trend_structure="bearish_intact",
            structure_intact=True,
            exit_on_close=last_close > trail,
            estimated_runner_pct=est,
        )

    confirmed_lh = float(lh_chain[-1][1])
    buf = _atr_buffer(confirmed_lh)
    trail = confirmed_lh + buf
    if float(floor_stop) > 0:
        trail = min(float(floor_stop), trail)

    structure_intact = True
    lh_idx = lh_chain[-1][0]
    for idx, px in pivot_highs:
        if idx > lh_idx and float(px) > confirmed_lh + buf * 0.5:
            structure_intact = False
            break

    est_low = float(min(lows[-12:])) if lows else last_close
    est = max(0.0, (last_close - est_low) / max(last_close, 1e-12) * 100.0)
    return TP3StructureSnapshot(
        trailing_stop=trail,
        confirmed_swing=confirmed_lh,
        next_swing_trigger=_next_lh_trigger(highs, confirmed_lh=confirmed_lh),
        trend_structure="broken" if not structure_intact else "bearish_intact",
        structure_intact=structure_intact,
        exit_on_close=bool(last_close > trail or not structure_intact),
        estimated_runner_pct=est,
    )


def apply_tp3_structure_trail(
    pos: Any,
    df15: pd.DataFrame,
    *,
    bar_ts: float,
    floor_stop: float,
) -> TP3StructureSnapshot:
    """
    Update runner trail state on a new closed 15m bar. Never widens risk vs prior stop.
    """
    snap = analyze_tp3_structure(
        df15,
        direction=str(pos.direction),
        entry=float(pos.entry),
        floor_stop=float(floor_stop),
    )
    is_long = str(pos.direction).upper() == "LONG"
    prior = float(getattr(pos, "tp3_trailing_stop", 0.0) or 0.0)
    new_stop = float(snap.trailing_stop)
    if prior > 0.0:
        if is_long:
            new_stop = max(prior, new_stop)
        else:
            new_stop = min(prior, new_stop)

    setattr(pos, "tp3_trailing_stop", float(new_stop))
    setattr(pos, "tp3_confirmed_swing", float(snap.confirmed_swing))
    setattr(pos, "tp3_next_swing_trigger", float(snap.next_swing_trigger))
    setattr(pos, "tp3_trend_structure", str(snap.trend_structure))
    setattr(pos, "tp3_estimated_runner_pct", float(snap.estimated_runner_pct))
    setattr(pos, "last_15m_bar_ts", float(bar_ts))
    # Keep exchange/hard-stop visibility on the structure trail; intrabar SL uses breakeven floor.
    pos.current_stop_loss = float(new_stop)

    exit_snap = TP3StructureSnapshot(
        trailing_stop=new_stop,
        confirmed_swing=snap.confirmed_swing,
        next_swing_trigger=snap.next_swing_trigger,
        trend_structure=snap.trend_structure,
        structure_intact=snap.structure_intact,
        exit_on_close=snap.exit_on_close,
        estimated_runner_pct=snap.estimated_runner_pct,
    )
    return exit_snap


def runner_floor_stop(pos: Any) -> float:
    """Breakeven floor for intrabar SL while the runner trails on 15m closes."""
    from position_management.post_tp1_stop import compute_post_tp1_stop_price

    floor = compute_post_tp1_stop_price(float(pos.entry), str(pos.direction), symbol=str(pos.symbol))
    is_long = str(pos.direction).upper() == "LONG"
    if is_long:
        return max(float(floor), float(pos.stop_loss))
    return min(float(floor), float(pos.stop_loss))


def format_trend_structure_label(raw: str) -> str:
    mapping = {
        "bullish_intact": "Bullish (15m HL intact)",
        "bearish_intact": "Bearish (15m LH intact)",
        "broken": "Structure broken",
        "pending": "Pending structure",
    }
    return mapping.get(str(raw), str(raw))


def tp3_exit_condition_text(*, direction: str, trailing_stop: float, structure: str) -> str:
    is_long = str(direction).upper() == "LONG"
    if structure == "broken":
        return "15m structure invalidated"
    if is_long:
        return f"15m close below {trailing_stop:.4f} trail"
    return f"15m close above {trailing_stop:.4f} trail"
