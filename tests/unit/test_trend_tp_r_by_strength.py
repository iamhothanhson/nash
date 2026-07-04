from __future__ import annotations

import pandas as pd

from risk.risk_multiplier_manager import (
    STRONG_TREND_THRESHOLD_MULTIPLIER,
    classify_ema20_slope_trend,
    classify_slope_trend,
)


def test_classify_slope_trend_bands() -> None:
    thr = 1.0
    assert classify_slope_trend(0.5, thr) == "weak"
    assert classify_slope_trend(1.5, thr) == "normal"
    assert classify_slope_trend(STRONG_TREND_THRESHOLD_MULTIPLIER * thr + 0.01, thr) == "strong"


def test_classify_ema20_slope_trend_strong_on_steep_series() -> None:
    # Monotonic rise → large positive EMA20 slope.
    close = pd.Series([100.0 + i * 2.0 for i in range(40)])
    df = pd.DataFrame({"close": close, "high": close, "low": close})
    assert classify_ema20_slope_trend(df) == "strong"


def test_classify_ema20_slope_trend_normal_on_flat_series() -> None:
    close = pd.Series([100.0] * 40)
    df = pd.DataFrame({"close": close, "high": close, "low": close})
    assert classify_ema20_slope_trend(df) == "weak"
