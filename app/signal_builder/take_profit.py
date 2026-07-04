"""Shared TP levels: TP1/TP2 from R multiples or 15m structure; TP3 from structure runner."""

from __future__ import annotations

from typing import Literal


def tp_from_r(
    *,
    entry: float,
    direction: str | Literal["LONG", "SHORT"],
    dist: float,
    tp_r: float,
) -> float:
    """Price at ``tp_r × stop distance`` from entry."""
    e = float(entry)
    d = float(dist)
    r = float(tp_r)
    if str(direction).upper() == "LONG":
        return e * (1.0 + r * d)
    return e * (1.0 - r * d)


def tp1_distance_frac(*, entry: float, direction: str, tp1: float) -> float:
    """Signed reward distance from entry to TP1 as a fraction of entry."""
    e = max(float(entry), 1e-12)
    if str(direction).upper() == "LONG":
        return (float(tp1) - e) / e
    return (e - float(tp1)) / e


def _clamp_tp_to_max_distance(
    *,
    entry: float,
    direction: str,
    tp_price: float,
    max_distance: float,
) -> float:
    cap = max(0.0, float(max_distance))
    if cap <= 0:
        return float(tp_price)
    cur = tp1_distance_frac(entry=float(entry), direction=direction, tp1=float(tp_price))
    if cur <= cap:
        return float(tp_price)
    e = float(entry)
    if str(direction).upper() == "LONG":
        return e * (1.0 + cap)
    return e * (1.0 - cap)


def clamp_tp1_to_max_distance(
    *,
    entry: float,
    direction: str,
    tp1: float,
    max_tp1_distance: float,
) -> float:
    """Cap TP1 reward distance at ``max_tp1_distance`` (0.025 = 2.5%)."""
    return _clamp_tp_to_max_distance(
        entry=float(entry),
        direction=direction,
        tp_price=float(tp1),
        max_distance=float(max_tp1_distance),
    )


def clamp_tp2_to_max_distance(
    *,
    entry: float,
    direction: str,
    tp2: float,
    max_tp2_distance: float,
) -> float:
    """Cap TP2 reward distance at ``max_tp2_distance`` (0.035 = 3.5%)."""
    return _clamp_tp_to_max_distance(
        entry=float(entry),
        direction=direction,
        tp_price=float(tp2),
        max_distance=float(max_tp2_distance),
    )


def _structure_profit_levels(
    *,
    entry: float,
    direction: str,
    data_15m,
    lookback: int,
    sep_frac: float,
    anchor: float | None,
) -> list[float]:
    """15m swing levels in profit direction from entry (nearest first)."""
    lookback_i = max(24, int(lookback))
    sep = max(0.0005, float(sep_frac))
    e = float(entry)
    window = data_15m.tail(lookback_i)
    if len(window) < 8:
        return []

    is_long = str(direction).upper() == "LONG"
    if is_long:
        min_px = e * (1.0 + sep)
        raw = {float(v) for v in window["high"].tolist() if float(v) >= min_px}
        if anchor is not None and float(anchor) >= min_px:
            raw.add(float(anchor))
        return sorted(raw)

    max_px = e * (1.0 - sep)
    raw = {float(v) for v in window["low"].tolist() if float(v) <= max_px}
    if anchor is not None and float(anchor) <= max_px:
        raw.add(float(anchor))
    return sorted(raw, reverse=True)


def resolve_tp1_price(
    *,
    entry: float,
    direction: str | Literal["LONG", "SHORT"],
    dist: float,
    tp1_r: float,
    max_tp1_distance: float | None = None,
) -> float:
    tp1 = tp_from_r(
        entry=float(entry),
        direction=direction,
        dist=float(dist),
        tp_r=float(tp1_r),
    )
    if max_tp1_distance is not None:
        tp1 = clamp_tp1_to_max_distance(
            entry=float(entry),
            direction=direction,
            tp1=tp1,
            max_tp1_distance=float(max_tp1_distance),
        )
    return tp1


def resolve_tp2_price(
    *,
    entry: float,
    direction: str | Literal["LONG", "SHORT"],
    dist: float,
    tp2_r: float,
    max_tp2_distance: float | None = None,
) -> float:
    """TP2 at ``tp2_r`` × stop distance (typically 2R), optionally capped per coin."""
    tp2 = tp_from_r(
        entry=float(entry),
        direction=direction,
        dist=float(dist),
        tp_r=float(tp2_r),
    )
    if max_tp2_distance is not None:
        tp2 = clamp_tp2_to_max_distance(
            entry=float(entry),
            direction=direction,
            tp2=tp2,
            max_tp2_distance=float(max_tp2_distance),
        )
    return tp2


def resolve_tp1_tp2_prices(
    *,
    entry: float,
    direction: str,
    dist: float,
    data_15m,
    cfg: dict | None,
    tp1_r: float,
    tp2_r: float,
    anchor: float | None = None,
) -> tuple[float, float]:
    from coins.loader import (
        resolve_max_tp1_distance,
        resolve_max_tp2_distance,
    )

    max_tp1 = resolve_max_tp1_distance(cfg) if cfg else None
    max_tp2 = resolve_max_tp2_distance(cfg) if cfg else None

    tp1 = resolve_tp1_price(
        entry=float(entry),
        direction=direction,
        dist=float(dist),
        tp1_r=float(tp1_r),
        max_tp1_distance=max_tp1,
    )
    tp2 = resolve_tp2_price(
        entry=float(entry),
        direction=direction,
        dist=float(dist),
        tp2_r=float(tp2_r),
        max_tp2_distance=max_tp2,
    )
    return tp1, tp2


def _tp3_structure_fallback(
    *,
    entry: float,
    direction: str,
    tp2: float,
    sep_frac: float,
) -> float:
    """Minimal TP3 when 15m window is too short or no swings qualify beyond TP2."""
    sep = max(0.0005, float(sep_frac))
    e = float(entry)
    t2 = float(tp2)
    if str(direction).upper() == "LONG":
        base = max(e, t2)
        return float(base * (1.0 + sep))
    base = min(e, t2)
    return float(base * (1.0 - sep))


def tp3_from_structure(
    *,
    entry: float,
    direction: str,
    data_15m,
    tp2: float,
    lookback: int,
    sep_frac: float,
) -> float:
    """Pick TP3 from 15m swing highs (LONG) or lows (SHORT) beyond TP2."""
    lookback_i = max(24, int(lookback))
    sep = max(0.0005, float(sep_frac))
    e = float(entry)
    t2 = float(tp2)
    window = data_15m.tail(lookback_i)
    if len(window) < 8:
        return _tp3_structure_fallback(entry=e, direction=direction, tp2=t2, sep_frac=sep)

    if str(direction).upper() == "LONG":
        raw = sorted(
            {float(v) for v in window["high"].tolist() if float(v) > e * (1.0 + sep)}
        )
        min_tp3 = max(t2, e * (1.0 + sep))
        levels = [v for v in raw if v >= min_tp3]
        if not levels:
            return _tp3_structure_fallback(entry=e, direction=direction, tp2=t2, sep_frac=sep)
        tp3 = next((v for v in levels if v > t2), levels[0])
        return float(max(tp3, t2 * (1.0 + sep)))

    raw = sorted(
        {float(v) for v in window["low"].tolist() if float(v) < e * (1.0 - sep)},
        reverse=True,
    )
    max_tp3 = min(t2, e * (1.0 - sep))
    levels = [v for v in raw if v <= max_tp3]
    if not levels:
        return _tp3_structure_fallback(entry=e, direction=direction, tp2=t2, sep_frac=sep)
    tp3 = next((v for v in levels if v < t2), levels[0])
    return float(min(tp3, t2 * (1.0 - sep)))
