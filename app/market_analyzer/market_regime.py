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


def build_regime_dict(
    data_15m: pd.DataFrame,
    data_1h: pd.DataFrame | None = None,
    *,
    market_structure: str | None = None,
    rsi: float | None = None,
    atr_percent: float | None = None,
    ema_slope: float | None = None,
) -> dict[str, Any]:
    close_15 = data_15m["close"].astype(float) if data_15m is not None and len(data_15m) else None

    adx_val = 0.0
    if data_15m is not None and len(data_15m) >= 19:
        try:
            adx_val = float(calculate_adx(data_15m, ADX_PERIOD_REGIME).iloc[-1])
        except Exception:
            pass

    atr_pct = 0.0
    atr_pctl = 50
    if data_15m is not None and len(data_15m) >= 14 and close_15 is not None:
        try:
            atr_series = calculate_atr(data_15m, ATR_PERIOD_REGIME)
            atr_v = float(atr_series.iloc[-1])
            atr_pct = atr_v / max(float(close_15.iloc[-1]), 1e-12)
            atr_pctl = _atr_percentile(atr_series, atr_v)
        except Exception:
            pass

    if atr_percent is not None:
        atr_pct = atr_percent
    if ema_slope is not None:
        ema_slp = ema_slope
    else:
        ema_slp = 0.0
        if data_15m is not None and len(data_15m) >= EMA_PERIOD_REGIME + SLOPE_LOOKBACK and close_15 is not None:
            try:
                ema20 = calculate_ema(data_15m, EMA_PERIOD_REGIME)
                ema_slp = float(ema20.iloc[-1] - ema20.iloc[-SLOPE_LOOKBACK]) / max(float(close_15.iloc[-1]), 1e-12)
            except Exception:
                pass

    vol_ratio = 1.0
    if data_15m is not None and "volume" in data_15m.columns:
        try:
            vol_ratio = _volume_ratio(data_15m["volume"].astype(float))
        except Exception:
            pass

    rsi_val = rsi if rsi is not None else 50.0
    if rsi is None and close_15 is not None and len(close_15) >= RSI_PERIOD_REGIME + 1:
        try:
            rsi_val = float(calculate_rsi(data_15m, RSI_PERIOD_REGIME).iloc[-1])
        except Exception:
            pass

    adx_1h_val: float | None = None
    ema_slope_1h_val: float | None = None
    if data_1h is not None and len(data_1h) >= 19:
        try:
            adx_1h_val = float(calculate_adx(data_1h, ADX_PERIOD_REGIME).iloc[-1])
        except Exception:
            pass
    if data_1h is not None and len(data_1h) >= 20:
        try:
            close_1h = data_1h["close"].astype(float)
            ema20_1h = calculate_ema(data_1h, EMA_PERIOD_REGIME)
            ema_slope_1h_val = float(ema20_1h.iloc[-1] - ema20_1h.iloc[-SLOPE_LOOKBACK]) / max(float(close_1h.iloc[-1]), 1e-12)
        except Exception:
            pass

    ms = market_structure if market_structure else "Range"
    trend_dir = _trend_direction(ema_slp)

    d: dict[str, Any] = {
        "adx": round(adx_val, 1),
        "atr_percent": round(atr_pct, 4),
        "atr_percentile": atr_pctl,
        "ema_slope": round(ema_slp, 6),
        "volume_ratio": round(vol_ratio, 2),
        "rsi": round(rsi_val, 1),
        "market_structure": ms,
        "trend_direction": trend_dir,
        "regime": _classify_regime(adx_val, atr_pctl, ema_slp, trend_dir, ms),
        "confidence": _regime_confidence(adx_val, ema_slp, vol_ratio, ms, trend_dir),
    }
    if adx_1h_val is not None:
        d["adx_1h"] = round(adx_1h_val, 1)
    if ema_slope_1h_val is not None:
        d["ema20_slope_1h"] = round(ema_slope_1h_val, 6)
    return d
