from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class Indicators:
    ema20_15m: Any = None
    ema20_1h: Any = None
    ema20_slope_15m: float | None = None
    ema20_slope_1h: float | None = None
    adx_15m: Any = None
    adx_1h: Any = None
    atr_15m: Any = None
    atr_percent: float | None = None
    atr_percentile: float | None = None
    rsi_15m: Any = None
    rsi: Any = None
    volume_sma20: float | None = None
    volume_ratio: float | None = None
    ema_slope: float | None = None
    symbol: str = ""
    timestamp: Any = None
