from __future__ import annotations

from typing import Any

import pandas as pd

from core.types import MarketRegime, MarketStructure
from indicators.volatility import _atr_percentile, calculate_atr
from indicators.volume import _volume_ratio
from indicators.momentum import calculate_rsi
from market_analyzer.market_trend import calculate_adx, calculate_ema

ATR_PERIOD_REGIME = 14
ADX_PERIOD_REGIME = 14
RSI_PERIOD_REGIME = 14
EMA_PERIOD_REGIME = 20
SLOPE_LOOKBACK = 5

from core.types import TrendDirection

def _trend_direction(ema_slope: float) -> TrendDirection:
    if ema_slope > 0.0003:
        return TrendDirection.BULLISH
    if ema_slope < -0.0003:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL


def _classify_regime(
    adx: float,
    atr_percentile: int,
    ema_slope: float,
    trend_dir: TrendDirection,
    market_structure: MarketStructure,
) -> MarketRegime:

    strong = (
        adx > 25
        and abs(ema_slope) > 0.001
        and market_structure in (MarketStructure.HHHL, MarketStructure.LHLL)
        and atr_percentile < 80
    )

    weak = adx < 20 or (
        adx < 23 and market_structure == MarketStructure.RANGE
    )

    hv = atr_percentile > 78

    if strong:
        if trend_dir == TrendDirection.BULLISH:
            return MarketRegime.STRONG_BULLISH
        if trend_dir == TrendDirection.BEARISH:
            return MarketRegime.STRONG_BEARISH

    if weak and hv:
        return MarketRegime.HIGH_VOLATILITY_CHOP

    if weak:
        if trend_dir == TrendDirection.BULLISH:
            return MarketRegime.WEAK_BULLISH
        if trend_dir == TrendDirection.BEARISH:
            return MarketRegime.WEAK_BEARISH
        return MarketRegime.RANGE

    if market_structure in (MarketStructure.HHHL, MarketStructure.LHLL) and adx >= 22:
        if trend_dir == TrendDirection.BULLISH:
            return MarketRegime.BULLISH
        if trend_dir == TrendDirection.BEARISH:
            return MarketRegime.BEARISH

    return MarketRegime.RANGE

from core.types import TrendDirection, MarketStructure

def _regime_confidence(
    adx: float,
    ema_slope: float,
    volume_ratio: float,
    market_structure: MarketStructure,
    trend_dir: TrendDirection,
) -> int:
    score = 50

    # ADX (0-20)
    if adx >= 35:
        score += 20
    elif adx >= 30:
        score += 15
    elif adx >= 25:
        score += 10
    elif adx >= 20:
        score += 5
    else:
        score -= 10

    # EMA slope (0-15)
    slope = abs(ema_slope)
    if slope >= 0.004:
        score += 15
    elif slope >= 0.002:
        score += 10
    elif slope >= 0.001:
        score += 5

    # Volume confirmation (0-10)
    if volume_ratio >= 1.5:
        score += 10
    elif volume_ratio >= 1.2:
        score += 7
    elif volume_ratio >= 1.0:
        score += 3

    # Market structure (0-10)
    if market_structure in (MarketStructure.HHHL, MarketStructure.LHLL):
        score += 10
    elif market_structure == MarketStructure.RANGE:
        score -= 5

    # Trend consistency (-10)
    if (
        ema_slope > 0 and trend_dir == TrendDirection.BEARISH
    ) or (
        ema_slope < 0 and trend_dir == TrendDirection.BULLISH
    ):
        score -= 10

    return max(0, min(100, round(score)))
