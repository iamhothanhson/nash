from dataclasses import dataclass
from types import SimpleNamespace

from app.core.types import Direction, MarketStructure
from indicators.models import Indicators
from market_analyzer.market_state import MarketState


@dataclass(frozen=True)
class ScoreResult:
    score: float


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

        score += self._score_strenth(features.breakout_strength_pct)
        score += self._score_volume(indicators.volume_ratio)
        score += self._score_rsi(side, indicators.rsi)
        score += self._score_ema_slope(indicators.ema_slope)
        score += self._score_candle_body(features.candle_body_ratio)
        score += self._score_market_structure(side, market_state)
        score += self._score_trend_alignment(market_state)
        score += self._score_htf_confirmation(features.htf_confirmed)

        return min(score, 100)

    @staticmethod
    def _score_volume(volume_ratio: float) -> int:
        if volume_ratio >= 2.0:
            return 20
        if volume_ratio >= 1.5:
            return 15
        if volume_ratio >= 1.2:
            return 10
        if volume_ratio >= 1.0:
            return 5
        return 0

    @staticmethod
    def _score_ema_slope(ema_slope: float) -> int:
        if ema_slope >= 0.003:
            return 15
        if ema_slope >= 0.002:
            return 10
        if ema_slope >= 0.001:
            return 5
        return 0

    @staticmethod
    def _score_candle_body(candle_body_ratio: float) -> int:
        if candle_body_ratio >= 0.80:
            return 10
        if candle_body_ratio >= 0.60:
            return 5
        return 0

    @staticmethod
    def _score_market_structure(side: str, market_state: MarketState) -> int:
        if side == "LONG" and market_state.structure == MarketStructure.HHHL:
            return 5
        if side == "SHORT" and market_state.structure == MarketStructure.LHLL:
            return 5
        return 0

    @staticmethod
    def _score_trend_alignment(market_state: MarketState) -> int:
        return 5 if market_state.trend_aligned else 0

    @staticmethod
    def _score_htf_confirmation(htf_confirmed: bool) -> int:
        return 5 if htf_confirmed else 0

    @staticmethod
    def _score_strenth(breakout_strength_pct):
        score = 0
        if breakout_strength_pct >= 0.008:
            score += 25
        elif breakout_strength_pct >= 0.006:
            score += 20
        elif breakout_strength_pct >= 0.004:
            score += 15
        elif breakout_strength_pct >= 0.003:
            score += 10
        elif breakout_strength_pct >= 0.002:
            score += 5
        return score

    @staticmethod
    def _score_rsi(side, rsi):
        score = 0
        if side == "LONG":
            if 60 <= rsi <= 68:
                score += 15      # Strong bullish momentum
            elif 55 <= rsi < 60:
                score += 10      # Good momentum
            elif 68 < rsi <= 72:
                score += 5       # Momentum is high but may be overextended
        
        if side == "SHORT":
            if 32 <= rsi <= 40:
                score += 15      # Strong bearish momentum
            elif 40 < rsi <= 45:
                score += 10      # Good bearish momentum
            elif 28 <= rsi < 32:
                score += 5       # Strong but may be oversold
        return score