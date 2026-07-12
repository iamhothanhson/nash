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

    has_hh = len(recent_highs) >= 2 and all(
        recent_highs[i + 1][1] > recent_highs[i][1] for i in range(len(recent_highs) - 1)
    )
    has_hl = len(recent_lows) >= 2 and all(
        recent_lows[i + 1][1] > recent_lows[i][1] for i in range(len(recent_lows) - 1)
    )
    has_lh = len(recent_highs) >= 2 and all(
        recent_highs[i + 1][1] < recent_highs[i][1] for i in range(len(recent_highs) - 1)
    )
    has_ll = len(recent_lows) >= 2 and all(
        recent_lows[i + 1][1] < recent_lows[i][1] for i in range(len(recent_lows) - 1)
    )

    if has_hh and has_hl:
        return MarketStructure.HHHL
    if has_lh and has_ll:
        return MarketStructure.LHLL
    if has_hh and not has_ll:
        return MarketStructure.HHHL
    if has_ll and not has_hh:
        return MarketStructure.LHLL
    return MarketStructure.RANGE
