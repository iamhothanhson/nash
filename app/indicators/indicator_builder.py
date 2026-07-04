from __future__ import annotations

from typing import Any

from .momentum import calculate_rsi
from .volatility import _atr_percentile, calculate_atr
from .volume import _volume_ratio
from market_analyzer.market_trend import calculate_adx, calculate_ema

calculate_atr = calculate_atr
calculate_ema = calculate_ema
calculate_rsi = calculate_rsi
calculate_adx = calculate_adx

SLOPE_LOOKBACK = 5


class IndicatorBuilder:
    @staticmethod
    def build(
        market_data: Any | None = None,
        symbol: str = "",
        timestamp: Any = None,
    ) -> dict[str, Any]:
        """Compute the shared indicator bundle for setup evaluation."""

        if market_data is not None:
            data_15m = market_data.get("15m")
            data_1h = market_data.get("1h")

        indicators: dict[str, Any] = {
            "ema20_15m": None,
            "ema20_1h": None,
            "ema20_slope_15m": None,
            "ema20_slope_1h": None,
            "adx_15m": None,
            "adx_1h": None,
            "atr_15m": None,
            "atr_percent": None,
            "atr_percentile": None,
            "rsi_15m": None,
            "volume_sma20": None,
            "volume_ratio": None,
            "symbol": symbol,
            "timestamp": timestamp,
        }

        # --- 15-minute indicators ---
        if data_15m is not None and len(data_15m) > 20:
            try:
                ema20_15 = calculate_ema(data_15m, 20)
                indicators["ema20_15m"] = ema20_15
                indicators["ema20_slope_15m"] = float(
                    ema20_15.iloc[-1] - ema20_15.iloc[-SLOPE_LOOKBACK]
                )
            except Exception:
                pass

            try:
                indicators["adx_15m"] = calculate_adx(data_15m, 14)
            except Exception:
                pass

            try:
                atr_s = calculate_atr(data_15m, 14)
                indicators["atr_15m"] = atr_s
                atr_v = float(atr_s.iloc[-1])
                close_v = float(data_15m["close"].iloc[-1])
                indicators["atr_percent"] = atr_v / max(close_v, 1e-12)
                indicators["atr_percentile"] = _atr_percentile(atr_s, atr_v)
            except Exception:
                pass

            try:
                indicators["rsi_15m"] = calculate_rsi(data_15m, 14)
            except Exception:
                pass

            try:
                vol = data_15m["volume"].astype(float)
                indicators["volume_sma20"] = float(vol.iloc[-20:].mean())
                indicators["volume_ratio"] = _volume_ratio(vol)
            except Exception:
                pass

        # --- 1-hour indicators ---
        if data_1h is not None and len(data_1h) > 20:
            try:
                ema20_1h = calculate_ema(data_1h, 20)
                indicators["ema20_1h"] = ema20_1h
                indicators["ema20_slope_1h"] = float(
                    ema20_1h.iloc[-1] - ema20_1h.iloc[-SLOPE_LOOKBACK]
                )
            except Exception:
                pass

            try:
                indicators["adx_1h"] = calculate_adx(data_1h, 14)
            except Exception:
                pass

        return indicators
