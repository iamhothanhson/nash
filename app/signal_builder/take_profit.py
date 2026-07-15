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


def clamp_tp3_to_max_distance(
    *,
    entry: float,
    direction: str,
    tp3: float,
    max_tp3_distance: float,
) -> float:
    """Cap TP3 reward distance at ``max_tp3_distance``."""
    return _clamp_tp_to_max_distance(
        entry=float(entry),
        direction=direction,
        tp_price=float(tp3),
        max_distance=float(max_tp3_distance),
    )


def resolve_tp3_price(
    *,
    entry: float,
    direction: str | Literal["LONG", "SHORT"],
    dist: float,
    tp3_r: float,
    max_tp3_distance: float | None = None,
) -> float:
    tp3 = tp_from_r(
        entry=float(entry),
        direction=direction,
        dist=float(dist),
        tp_r=float(tp3_r),
    )
    if max_tp3_distance is not None:
        tp3 = clamp_tp3_to_max_distance(
            entry=float(entry),
            direction=direction,
            tp3=tp3,
            max_tp3_distance=float(max_tp3_distance),
        )
    return tp3


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
