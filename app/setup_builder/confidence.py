from __future__ import annotations

from typing import Any


def compute_breakout_confidence(
    strength: float,
    strength_threshold: float,
    ema_slope: float,
    rsi: float,
    volume_ratio: float,
    atr_pct: float,
    direction: str,
    config: dict[str, Any],
) -> float:
    score = 0

    # 1. Breakout strength (30)
    if strength >= strength_threshold * 2.0:
        score += 30
    elif strength >= strength_threshold * 1.5:
        score += 25
    elif strength >= strength_threshold:
        score += 20

    # 2. Volume confirmation (25)
    if volume_ratio >= 2.0:
        score += 25
    elif volume_ratio >= 1.5:
        score += 20
    elif volume_ratio >= config["min_volume_ratio"]:
        score += 15

    # 3. Trend alignment (20)
    slope = ema_slope if direction == "LONG" else -ema_slope
    ema_min = config["ema_slope_min"]
    if slope >= ema_min * 2:
        score += 20
    elif slope >= ema_min * 1.5:
        score += 16
    elif slope >= ema_min:
        score += 12

    # 4. Momentum (15)
    if direction == "LONG":
        if rsi >= 65:
            score += 15
        elif rsi >= 60:
            score += 12
        elif rsi >= config["long_rsi_min"]:
            score += 8
    else:
        if rsi <= 35:
            score += 15
        elif rsi <= 40:
            score += 12
        elif rsi <= config["short_rsi_max"]:
            score += 8

    # 5. Breakout quality relative to ATR (10)
    atr_ratio = strength / max(atr_pct, 1e-12)
    if atr_ratio >= 2.0:
        score += 10
    elif atr_ratio >= 1.5:
        score += 8
    elif atr_ratio >= 1.0:
        score += 5

    return min(score, 100) / 100.0
