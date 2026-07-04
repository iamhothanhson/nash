from __future__ import annotations

import pandas as pd

ATR_PERCENTILE_WINDOW = 96


def _atr_percentile(atr_series: pd.Series, value: float, window: int = ATR_PERCENTILE_WINDOW) -> int:
    if len(atr_series) < 10:
        return 50
    tail = atr_series.iloc[-window:]
    count_below = int((tail < value).sum())
    return min(100, max(0, int(count_below / len(tail) * 100)))


def calculate_atr(data: pd.DataFrame, period: int) -> pd.Series:
    prev_close = data["close"].shift(1)
    tr = pd.concat(
        [
            (data["high"] - data["low"]).abs(),
            (data["high"] - prev_close).abs(),
            (data["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()
