from datetime import datetime, timezone

from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.feature_builder import build_features
from market_analyzer.market_regime import _classify_regime, _regime_confidence, _trend_direction
from market_analyzer.market_state import (
    MarketRegime,
    MarketState,
    MarketStructure,
    TrendDirection,
)
from market_analyzer.market_structure import detect_market_structure
from market_analyzer.market_trend import calculate_adx
from setup_builder.builder import SetupBuilder
from setup_builder.models import Setup


class MarketAnalyzer:

    def build_market_state(
        self,
        symbol: str,
        data=None,
        indicators=None,
    ) -> Setup:
        if data is not None:
            data_5m = data.get("5m") 
            data_15m = data.get("15m")
            data_1h = data.get("1h")

        timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        ms_1h = detect_market_structure(data_1h["high"], data_1h["low"]) if data_1h is not None else "RANGE"

        ms_15m = detect_market_structure(data_15m["high"], data_15m["low"]) if data_15m is not None else "RANGE"

        adx_v = 0.0
        if data_15m is not None and len(data_15m) >= 14:
            try:
                adx_v = float(calculate_adx(data_15m, 14).iloc[-1])
            except Exception:
                pass

        ema_slp = indicators.get("ema20_slope_15m") or 0.0
        vol_r = indicators.get("volume_ratio") or 1.0
        atr_pctl = indicators.get("atr_percentile") or 50

        trend_dir_str = _trend_direction(ema_slp)
        trend_dir = (
            TrendDirection.BULLISH if trend_dir_str.lower() == "bullish"
            else TrendDirection.BEARISH if trend_dir_str.lower() == "bearish"
            else TrendDirection.NEUTRAL
        )

        regime_str = _classify_regime(adx_v, atr_pctl, ema_slp, trend_dir_str, ms_15m)
        regime = _map_regime(regime_str)
        structure = _map_structure(ms_1h)
        rc = float(_regime_confidence(adx_v, ema_slp, vol_r, ms_15m, trend_dir_str))

        is_trending = regime in (
            MarketRegime.STRONG_BULLISH, MarketRegime.BULLISH,
            MarketRegime.BEARISH, MarketRegime.STRONG_BEARISH,
        )
        is_ranging = regime == MarketRegime.RANGE
        is_high_volatility = regime == MarketRegime.HIGH_VOLATILITY_CHOP

        sa = (
            "aligned" if ms_1h == ms_15m
            else "neutral" if "Range" in (ms_1h, ms_15m)
            else "conflict"
        )
        trend_aligned = sa == "aligned"

        features = build_features(
            data_15m=data_15m,
            indicators=indicators,
        )
        market_state = MarketState(
            symbol=symbol,
            timestamp=timestamp,
            timeframe="15m",
            trend_direction=trend_dir,
            trend_aligned=trend_aligned,
            regime=regime,
            structure=structure,
            regime_confidence=rc,
            is_trending=is_trending,
            is_ranging=is_ranging,
            is_high_volatility=is_high_volatility,
            indicators=indicators,
            features=features,
            data_5m=data_5m,
            data_15m=data_15m,
            data_1h=data_1h,
        )

        return market_state


def _map_regime(reg: str) -> MarketRegime:
    mapping = {
        "Strong Bullish": MarketRegime.STRONG_BULLISH,
        "Moderate Bullish": MarketRegime.WEAK_BULLISH,
        "Neutral / Range": MarketRegime.RANGE,
        "Weak / Choppy": MarketRegime.WEAK_BEARISH,
        "Moderate Bearish": MarketRegime.WEAK_BEARISH,
        "Strong Bearish": MarketRegime.STRONG_BEARISH,
        "High Volatility Chop": MarketRegime.HIGH_VOLATILITY_CHOP,
    }
    return mapping.get(reg, MarketRegime.RANGE)


def _map_structure(ms: str) -> MarketStructure:
    mapping = {
        "HHHL": MarketStructure.HHHL,
        "LHLL": MarketStructure.LHLL,
        "Range": MarketStructure.RANGE,
    }
    return mapping.get(ms, MarketStructure.UNKNOWN)
