from dataclasses import dataclass
from types import SimpleNamespace

from app.core.types import Direction, MarketStructure
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
        score = 0
        score += self._score_strength(features.breakout_strength)
        score += self._score_volume(indicators.volume_ratio)
        score += self._score_rsi(side, indicators.rsi)
        score += self._score_ema_slope(indicators.ema_slope)
        score += self._score_candle_body(features.candle_body_ratio)
        score += self._score_market_structure(side, market_state)
        score += self._score_trend_alignment(market_state)
        score += self._score_htf_confirmation(features.htf_confirmed)

        return min(score, 100)

    @staticmethod
    def _score_strength(breakout_strength: float) -> int:
        if breakout_strength >= 0.0080:
            return 25
        if breakout_strength >= 0.0060:
            return 20
        if breakout_strength >= 0.0045:
            return 15
        if breakout_strength >= BREAKOUT_MIN_STRENGTH:
            return 10
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
    def _score_rsi(side: str, rsi: float) -> int:
        # Max: 15
        if side == "LONG":
            if 60 <= rsi <= 68:
                return 15
            if 55 <= rsi < 60:
                return 10
            if 68 < rsi <= 72:
                return 5

        if side == "SHORT":
            if 32 <= rsi <= 40:
                return 15
            if 40 < rsi <= 45:
                return 10
            if 28 <= rsi < 32:
                return 5

        return 0


    @staticmethod
    def _score_ema_slope(ema_slope: float) -> int:
        # Max: 15
        if ema_slope >= 0.003:
            return 15
        if ema_slope >= 0.002:
            return 10
        if ema_slope >= 0.001:
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
        return 0


    @staticmethod
    def _score_trend_alignment(market_state: MarketState) -> int:
        # Max: 10
        return 10 if market_state.trend_aligned else 0


    @staticmethod
    def _score_htf_confirmation(htf_confirmed: bool) -> int:
        # Max: 5
        return 5 if htf_confirmed else 0