from __future__ import annotations

import pandas as pd

from core.types import MarketStructure


def detect_market_structure(high: pd.Series, low: pd.Series, lookback: int = 40) -> MarketStructure:
    """Classify market structure as HHHL (bullish), LHLL (bearish), or RANGE."""
    if len(high) < 12:
        return MarketStructure.RANGE
    tail = min(lookback, len(high) - 4)
    if tail < 10:
        return MarketStructure.RANGE

    swings_high: list[tuple[int, float]] = []
    swings_low: list[tuple[int, float]] = []

    for i in range(2, len(high) - 2):
        if (
            high.iloc[i] > high.iloc[i - 1]
            and high.iloc[i] > high.iloc[i - 2]
            and high.iloc[i] > high.iloc[i + 1]
            and high.iloc[i] > high.iloc[i + 2]
        ):
            swings_high.append((i, float(high.iloc[i])))
        if (
            low.iloc[i] < low.iloc[i - 1]
            and low.iloc[i] < low.iloc[i - 2]
            and low.iloc[i] < low.iloc[i + 1]
            and low.iloc[i] < low.iloc[i + 2]
        ):
            swings_low.append((i, float(low.iloc[i])))

    min_idx = len(high) - tail
    recent_highs = [p for p in swings_high if p[0] >= min_idx]
    recent_lows = [p for p in swings_low if p[0] >= min_idx]

    def _trend_ratio(points: list[tuple[int, float]]) -> float:
        if len(points) < 2:
            return 0.0
        up = sum(1 for i in range(len(points) - 1) if points[i + 1][1] > points[i][1])
        return up / (len(points) - 1)

    hh_ratio = _trend_ratio(recent_highs)
    hl_ratio = _trend_ratio(recent_lows)
    lh_ratio = 1 - hh_ratio
    ll_ratio = 1 - hl_ratio

    has_hh = hh_ratio >= 0.5
    has_hl = hl_ratio >= 0.5
    has_lh = lh_ratio >= 0.5
    has_ll = ll_ratio >= 0.5

    if has_hh and has_hl:
        return MarketStructure.HHHL
    if has_lh and has_ll:
        return MarketStructure.LHLL
    if has_hh and not has_ll:
        return MarketStructure.HHHL
    if has_ll and not has_hh:
        return MarketStructure.LHLL
    return MarketStructure.RANGE
