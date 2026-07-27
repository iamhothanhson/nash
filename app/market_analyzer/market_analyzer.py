from datetime import datetime, timezone

from core.types import MarketRegime, MarketStructure
from market_analyzer.market_regime import classify_market_regime, regime_score, _regime_confidence
from market_analyzer.market_state import MarketState
from market_analyzer.market_structure import detect_market_structure
from setup_builder.models import Setup
from market_analyzer.market_regime import _trend_direction


class MarketAnalyzer:

    def build_market_state(
        self,
        symbol: str,
        data=None,
        indicators=None,
        timestamp: int | None = None,
    ) -> Setup:
        if data is not None:
            data_5m = data.get("5m") 
            data_15m = data.get("15m")
            data_1h = data.get("1h")

        if timestamp is None:
            timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        ms_1h = detect_market_structure(data_1h["high"], data_1h["low"]) if data_1h is not None else MarketStructure.RANGE

        ms_15m = detect_market_structure(data_15m["high"], data_15m["low"]) if data_15m is not None else MarketStructure.RANGE

        adx_v = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0.0
        ema_slp = indicators.ema20_slope_15m or 0.0
        vol_r = indicators.volume_ratio or 1.0
        atr_pctl = indicators.atr_percentile or 50
        trend_dir = _trend_direction(ema_slp)

        score = regime_score(
            trend_direction=trend_dir,
            ema_slope_1h=ema_slp,
            adx_1h=adx_v,
            market_structure_1h=ms_1h,
            atr_percentile_15m=atr_pctl,
            volume_ratio_15m=vol_r,
        )
        regime = classify_market_regime(score, atr_percentile_15m=atr_pctl, adx_1h=adx_v)
        rc = float(_regime_confidence(score))

        is_trending = regime in (
            MarketRegime.STRONG_BULLISH, MarketRegime.BULLISH,
            MarketRegime.BEARISH, MarketRegime.STRONG_BEARISH,
        )
        is_ranging = regime == MarketRegime.RANGE
        is_high_volatility = regime == MarketRegime.HIGH_VOLATILITY_CHOP

        sa = (
            "aligned" if ms_1h == ms_15m
            else "neutral" if any(ms == MarketStructure.RANGE for ms in (ms_1h, ms_15m))
            else "conflict"
        )
        trend_aligned = sa == "aligned"

        market_state = MarketState(
            symbol=symbol,
            timestamp=timestamp,
            timeframe="15m",
            trend_direction=trend_dir,
            trend_aligned=trend_aligned,
            regime=regime,
            market_structure_1h=ms_1h,
            regime_confidence=rc,
            is_trending=is_trending,
            is_ranging=is_ranging,
            is_high_volatility=is_high_volatility,
            indicators=indicators,
            data_5m=data_5m,
            data_15m=data_15m,
            data_1h=data_1h,
        )

        return market_state
