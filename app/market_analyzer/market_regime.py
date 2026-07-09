from __future__ import annotations

from typing import Any

import pandas as pd

from indicators.volatility import _atr_percentile, calculate_atr
from indicators.volume import _volume_ratio
from indicators.momentum import calculate_rsi
from market_analyzer.market_trend import calculate_adx, calculate_ema

ATR_PERIOD_REGIME = 14
ADX_PERIOD_REGIME = 14
RSI_PERIOD_REGIME = 14
EMA_PERIOD_REGIME = 20
SLOPE_LOOKBACK = 5

def _trend_direction(ema_slope: float) -> str:
    if ema_slope > 0.0003:
        return "Bullish"
    if ema_slope < -0.0003:
        return "Bearish"
    return "Neutral"


def _classify_regime(
    adx: float,
    atr_percentile: int,
    ema_slope: float,
    trend_dir: str,
    market_structure: str,
) -> str:
    strong = adx > 25 and abs(ema_slope) > 0.001 and market_structure in ("HHHL", "LHLL") and atr_percentile < 80
    weak = adx < 20 or (adx < 23 and market_structure == "Range")
    hv = atr_percentile > 78
    if strong:
        return f"Strong {trend_dir}"
    if weak and hv:
        return "High Volatility Chop"
    if weak:
        return "Weak/Choppy"
    if market_structure in ("HHHL", "LHLL") and adx >= 22:
        return f"Moderate {trend_dir}"
    return "Neutral/Range"


def _regime_confidence(
    adx: float,
    ema_slope: float,
    volume_ratio: float,
    market_structure: str,
    trend_dir: str,
) -> int:
    score = 50
    if adx > 28:
        score += 15
    elif adx > 22:
        score += 8
    if abs(ema_slope) > 0.003:
        score += 10
    elif abs(ema_slope) > 0.001:
        score += 5
    if volume_ratio > 1.3:
        score += 10
    elif volume_ratio > 1.0:
        score += 5
    if market_structure in ("HHHL", "LHLL"):
        score += 10
    if adx < 20 and market_structure == "Range":
        score -= 10
    if (ema_slope > 0.0003 and trend_dir == "Bearish") or (
        ema_slope < -0.0003 and trend_dir == "Bullish"
    ):
        score -= 10
    return max(10, min(100, score))
