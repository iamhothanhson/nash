from dataclasses import dataclass
from types import SimpleNamespace

from app.core.logger import logger
from app.core.types import Direction, MarketStructure
from app.market_analyzer import market_structure
from app.strategy.trend_following.breakout.config import BREAKOUT_MIN_STRENGTH
from indicators.models import Indicators
from market_analyzer.market_state import MarketState


class Scorer:
    
    def score_breakout_setup(
        self,
        features: dict,
        indicators: Indicators,
        market_state: MarketState,
        side: str,
    ) -> int:
        features = SimpleNamespace(**features)
        adx_15m = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0
        adx_1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0

        strength = self._score_strength(features.breakout_strength)
        volume = self._score_volume(indicators.volume_ratio)
        rsi = self._score_rsi(side, indicators.rsi)
        ema = self._score_ema_slope(side, indicators.ema20_slope_15m)
        body = self._score_candle_body(features.candle_body_ratio)
        structure = self._score_market_structure(side, market_state)
        htf = self._score_htf_confirmation(features.htf_confirmed)
        adx = self._score_adx(adx_15m, adx_1h)

        total = (
            strength + volume + rsi + ema +
            body + structure + htf + adx
        )

        logger.info(
            "%s score=%d | "
            "strength=%d(%.4f) "
            "volume=%d(%.2f) "
            "rsi=%d(%.1f) "
            "ema=%d(%.6f) "
            "body=%d(%.2f) "
            "structure=%d(%s) "
            "adx=%d(%.1f/%.1f) "
            "htf=%d(%s)",
            side,
            total,
            strength, features.breakout_strength,
            volume, indicators.volume_ratio,
            rsi, indicators.rsi,
            ema, indicators.ema20_slope_15m,
            body, features.candle_body_ratio,
            structure, market_state.structure.name,
            adx, adx_15m, adx_1h,
            htf, features.htf_confirmed,
        )

        return total

    @staticmethod
    def _score_strength(breakout_strength: float) -> int:
        """Max: 15"""
        if breakout_strength >= 0.0080:
            return 15
        if breakout_strength >= 0.0060:
            return 10
        if breakout_strength >= 0.0045:
            return 5
        if breakout_strength >= BREAKOUT_MIN_STRENGTH:
            return 0
        return 0  # Should never happen


    @staticmethod
    def _score_volume(volume_ratio: float) -> int:
        # Max: 15
        if volume_ratio >= 2.0:
            return 15
        if volume_ratio >= 1.5:
            return 10
        if volume_ratio >= 1.2:
            return 5
        return 0
    
    @staticmethod
    def _score_adx(adx_15m: float, adx_1h: float) -> int:
        if adx_15m >= 35 and adx_1h >= 35:
            return 10
        if adx_15m >= 28 and adx_1h >= 28:
            return 5
        return 0


    @staticmethod
    def _score_rsi(side: str, rsi: float) -> int:
        # Max: 15
        if side == "LONG":
            if 65 <= rsi <= 80:
                return 15
            if 55 <= rsi < 65:
                return 10
            if 80 < rsi <= 85:
                return 5
            return 0

        if side == "SHORT":
            if 20 <= rsi <= 35:
                return 15
            if 35 < rsi <= 45:
                return 10
            if 15 <= rsi < 20:
                return 5
            return 0

        return 0


    @staticmethod
    def _score_ema_slope(side: str, ema_slope: float) -> int:
        if side == "LONG":
            if ema_slope >= 0.003:
                return 15
            if ema_slope >= 0.002:
                return 10
            if ema_slope >= 0.001:
                    return 5
        else:
            if ema_slope <= -0.003:
                return 15
            if ema_slope <= -0.002:
                return 10
            if ema_slope <= -0.001:
                return 5

        return 0


    @staticmethod
    def _score_candle_body(candle_body_ratio: float) -> int:
        # Max: 10
        if candle_body_ratio >= 0.80:
            return 10
        if candle_body_ratio >= 0.60:
            return 5
        return 0


    @staticmethod
    def _score_market_structure(side: str, market_state: MarketState) -> int:
        # Max: 10
        if side == "LONG" and market_state.structure == MarketStructure.HHHL:
            return 10
        if side == "SHORT" and market_state.structure == MarketStructure.LHLL:
            return 10
        if market_state.structure == MarketStructure.RANGE:
            return 5
        return 0


    @staticmethod
    def _score_htf_confirmation(htf_confirmed: bool) -> int:
        # Max: 10
        return 10 if htf_confirmed else 0