from __future__ import annotations

from typing import Iterable

import pandas as pd

from market_analyzer.market_trend import _precomputed_col


def calculate_rsi(values: Iterable[float] | pd.DataFrame, period: int = 14) -> pd.Series:
    if isinstance(values, pd.DataFrame):
        col = f"rsi_{period}"
        cached = _precomputed_col(values, col, period)
        if cached is not None:
            return cached
        values = values["close"]
    series = pd.Series(values, dtype="float64")
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def rsi_latest(values: Iterable[float] | pd.DataFrame | pd.Series, period: int = 14) -> float:
    if isinstance(values, pd.Series):
        series = values
    else:
        series = calculate_rsi(values, period)
    if series.empty:
        return 0.0
    val = series.iloc[-1]
    if pd.isna(val):
        return 0.0
    return float(val)
