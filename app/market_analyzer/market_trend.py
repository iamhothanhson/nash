from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd


def _precomputed_col(data: pd.DataFrame, col: str, min_len: int = 0) -> pd.Series | None:
    if col in data.columns and len(data) > min_len:
        last = data[col].iloc[-1]
        if pd.notna(last):
            return data[col]
    return None


def calculate_ema(values: Iterable[float] | pd.DataFrame, period: int) -> pd.Series:
    if isinstance(values, pd.DataFrame):
        col = f"ema_{period}"
        cached = _precomputed_col(values, col, period)
        if cached is not None:
            return cached
        values = values["close"]
    series = pd.Series(values, dtype="float64")
    return series.ewm(span=period, adjust=False).mean()


def calculate_adx(data: pd.DataFrame, period: int = 14) -> pd.Series:
    """Wilder ADX (Average Directional Index) from OHLCV."""
    high = data["high"].astype(float)
    low = data["low"].astype(float)
    close = data["close"].astype(float)
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low).abs(),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = ((up_move > down_move) & (up_move > 0)) * up_move
    minus_dm = ((down_move > up_move) & (down_move > 0)) * down_move
    alpha = 1.0 / float(period)
    atr_w = tr.ewm(alpha=alpha, adjust=False).mean()
    plus_di = 100.0 * (plus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w.replace(0, pd.NA))
    minus_di = 100.0 * (minus_dm.ewm(alpha=alpha, adjust=False).mean() / atr_w.replace(0, pd.NA))
    den = (plus_di + minus_di).replace(0, np.nan)
    dx = (abs(plus_di - minus_di) / den) * 100.0
    dx = pd.to_numeric(dx, errors="coerce")
    dx = dx.replace([np.inf, -np.inf], np.nan).fillna(0.0)
    adx = dx.ewm(alpha=alpha, adjust=False).mean()
    return adx.fillna(0.0)
