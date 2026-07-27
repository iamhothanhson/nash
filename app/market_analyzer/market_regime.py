from __future__ import annotations

from typing import Any

import pandas as pd

from core.types import MarketRegime, MarketStructure, TrendDirection

ATR_PERIOD_REGIME = 14
ADX_PERIOD_REGIME = 14
RSI_PERIOD_REGIME = 14
EMA_PERIOD_REGIME = 20
SLOPE_LOOKBACK = 5


def _trend_direction_score(trend_direction: TrendDirection) -> int:
    if trend_direction == TrendDirection.BULLISH:
        return 20
    if trend_direction == TrendDirection.BEARISH:
        return -20
    return 0


def _ema_slope_score(ema_slope_1h: float, trend_direction: TrendDirection) -> int:
    slope = abs(ema_slope_1h)
    if slope >= 0.004:
        score = 20
    elif slope >= 0.002:
        score = 15
    elif slope >= 0.001:
        score = 10
    elif slope >= 0.0005:
        score = 5
    else:
        score = 0
    return score if trend_direction == TrendDirection.BULLISH else -score if trend_direction == TrendDirection.BEARISH else 0


def _adx_score(adx_1h: float, trend_direction: TrendDirection) -> int:
    if adx_1h >= 35:
        score = 20
    elif adx_1h >= 30:
        score = 15
    elif adx_1h >= 25:
        score = 10
    elif adx_1h >= 20:
        score = 5
    else:
        score = 0
    return score if trend_direction == TrendDirection.BULLISH else -score if trend_direction == TrendDirection.BEARISH else 0


def _market_structure_score(market_structure_1h: MarketStructure, current_score: int) -> int:
    if market_structure_1h == MarketStructure.HHHL:
        return 20
    if market_structure_1h == MarketStructure.LHLL:
        return -20
    if market_structure_1h == MarketStructure.RANGE:
        return -10 if current_score > 0 else 10 if current_score < 0 else 0
    return 0


def _volume_ratio_score(volume_ratio_15m: float, trend_direction: TrendDirection) -> int:
    if volume_ratio_15m >= 1.5:
        score = 10
    elif volume_ratio_15m >= 1.2:
        score = 5
    else:
        score = 0
    return score if trend_direction == TrendDirection.BULLISH else -score if trend_direction == TrendDirection.BEARISH else 0


def _atr_penalty(atr_percentile_15m: int, score: int) -> int:
    if atr_percentile_15m >= 90:
        return int(score * 0.6)
    if atr_percentile_15m >= 80:
        return int(score * 0.8)
    return score


def regime_score(
    *,
    trend_direction: TrendDirection,
    ema_slope_1h: float,
    adx_1h: float,
    market_structure_1h: MarketStructure,
    atr_percentile_15m: int,
    volume_ratio_15m: float,
) -> int:
    score = _trend_direction_score(trend_direction)
    score += _ema_slope_score(ema_slope_1h, trend_direction)
    score += _adx_score(adx_1h, trend_direction)
    score += _market_structure_score(market_structure_1h, score)
    score += _volume_ratio_score(volume_ratio_15m, trend_direction)
    score = _atr_penalty(atr_percentile_15m, score)
    return max(-100, min(100, score))


def classify_market_regime(
    score: int,
    *,
    atr_percentile_15m: int,
    adx_1h: float,
) -> MarketRegime:

    # High volatility + weak trend
    if atr_percentile_15m >= 80 and adx_1h < 20:
        return MarketRegime.HIGH_VOLATILITY_CHOP

    if score >= 70:
        return MarketRegime.STRONG_BULLISH

    if score >= 40:
        return MarketRegime.BULLISH

    if score >= 15:
        return MarketRegime.WEAK_BULLISH

    if score <= -70:
        return MarketRegime.STRONG_BEARISH

    if score <= -40:
        return MarketRegime.BEARISH

    if score <= -15:
        return MarketRegime.WEAK_BEARISH

    return MarketRegime.RANGE

def _regime_confidence(score: int) -> int:
    return min(100, abs(score))

def _trend_direction(ema_slope: float) -> TrendDirection:
    if ema_slope > 0.0003:
        return TrendDirection.BULLISH
    if ema_slope < -0.0003:
        return TrendDirection.BEARISH
    return TrendDirection.NEUTRAL