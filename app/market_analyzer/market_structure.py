from __future__ import annotations

import pandas as pd

from market_analyzer.config import MARKET_STRUCTURE_SWING_LOOKBACK
from core.types import MarketStructure


def detect_market_structure(
    high: pd.Series,
    low: pd.Series,
    lookback: int = MARKET_STRUCTURE_SWING_LOOKBACK,
) -> MarketStructure:
    """
    Detect market structure using the latest confirmed swing highs/lows.

    HHHL  = Higher Highs + Higher Lows
    LHLL  = Lower Highs + Lower Lows
    RANGE = Mixed structure or insufficient data
    """

    if len(high) < 20:
        return MarketStructure.RANGE

    swings_high: list[tuple[int, float]] = []
    swings_low: list[tuple[int, float]] = []

    # Confirmed 5-bar pivots
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

    min_idx = len(high) - lookback

    recent_highs = [p for p in swings_high if p[0] >= min_idx][-4:]
    recent_lows = [p for p in swings_low if p[0] >= min_idx][-4:]

    if len(recent_highs) < 3 or len(recent_lows) < 3:
        return MarketStructure.RANGE

    def trend_score(values: list[float]) -> int:
        score = 0
        for i in range(len(values) - 1):
            if values[i + 1] > values[i]:
                score += 1
            elif values[i + 1] < values[i]:
                score -= 1
        return score

    high_values = [x[1] for x in recent_highs]
    low_values = [x[1] for x in recent_lows]

    high_score = trend_score(high_values)
    low_score = trend_score(low_values)

    # Strong bullish structure
    if high_score >= 2 and low_score >= 2:
        return MarketStructure.HHHL

    # Strong bearish structure
    if high_score <= -2 and low_score <= -2:
        return MarketStructure.LHLL

    return MarketStructure.RANGE