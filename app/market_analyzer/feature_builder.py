from __future__ import annotations

from typing import get_args

import pandas as pd

from core.types import Direction, MarketStructure
from market_analyzer.market_structure import detect_market_structure
from market_analyzer.models import BreakoutFeatures, SetupFeatures

_VALID_STRUCTURES = get_args(MarketStructure)


def compute_breakout_features(
    data_15m: pd.DataFrame | None,
    indicators: dict | None = None,
) -> BreakoutFeatures:
    if data_15m is None or len(data_15m) < 10:
        return BreakoutFeatures(
            direction="LONG",
            breakout_level=0.0,
            close_above_level=False,
            breakout_strength_pct=0.0,
            distance_from_level_pct=0.0,
            candle_body_ratio=0.0,
            wick_ratio=0.0,
            touch_count=0,
            breakout_level_age=0,
            market_structure="UNKNOWN",
            htf_confirmed=False,
        )

    high = data_15m["high"]
    low = data_15m["low"]
    close = data_15m["close"]
    ohlc_open = data_15m["open"]

    lookback = min(20, len(data_15m) - 3)
    recent_high = float(high.iloc[-lookback:-1].max())
    recent_low = float(low.iloc[-lookback:-1].min())
    current_close = float(close.iloc[-1])
    current_high = float(high.iloc[-1])
    current_low = float(low.iloc[-1])
    current_open = float(ohlc_open.iloc[-1])

    close_above = current_close > recent_high
    close_below = current_close < recent_low

    if close_above:
        direction: Direction = "LONG"
        breakout_level = recent_high
    elif close_below:
        direction = "SHORT"
        breakout_level = recent_low
    else:
        return BreakoutFeatures(
            direction="LONG",
            breakout_level=0.0,
            close_above_level=False,
            breakout_strength_pct=0.0,
            distance_from_level_pct=0.0,
            candle_body_ratio=0.0,
            wick_ratio=0.0,
            touch_count=0,
            breakout_level_age=0,
            market_structure="UNKNOWN",
            htf_confirmed=False,
        )

    dist = (
        (current_close - breakout_level) / breakout_level * 100
        if direction == "LONG"
        else (breakout_level - current_close) / breakout_level * 100
    )
    distance_pct = max(dist, 0.0)

    candle_range = current_high - current_low
    body = abs(current_close - current_open)
    body_ratio = body / candle_range if candle_range > 0 else 0.0
    wick_ratio = (candle_range - body) / candle_range if candle_range > 0 else 0.0

    touch_count = 0
    breakout_level_age = 0
    for i in range(-min(30, len(data_15m)), -1):
        c = float(close.iloc[i])
        if breakout_level > 0 and abs(c - breakout_level) / breakout_level < 0.002:
            touch_count += 1
            if breakout_level_age == 0:
                breakout_level_age = abs(i)

    ms = detect_market_structure(high, low, lookback=20)
    market_structure: MarketStructure = ms if ms in _VALID_STRUCTURES else _VALID_STRUCTURES[3]

    htf_ema_slope = indicators.ema20_slope_1h

    htf_confirmed = (
        (direction == "LONG" and htf_ema_slope > 0)
        or (direction == "SHORT" and htf_ema_slope < 0)
    )

    return BreakoutFeatures(
        direction=direction,
        breakout_level=breakout_level,
        close_above_level=close_above or direction == "LONG",
        breakout_strength_pct=distance_pct,
        distance_from_level_pct=distance_pct,
        candle_body_ratio=body_ratio,
        wick_ratio=wick_ratio,
        touch_count=touch_count,
        breakout_level_age=breakout_level_age,
        market_structure=market_structure,
        htf_confirmed=htf_confirmed,
    )


def build_features(
    data_15m: pd.DataFrame | None = None,
    indicators: dict | None = None,
) -> SetupFeatures:
    features = SetupFeatures.empty()
    features.breakout = compute_breakout_features(data_15m, data_1h, indicators)
    return features
