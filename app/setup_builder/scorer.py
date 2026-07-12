from dataclasses import dataclass
from types import SimpleNamespace

from indicators.models import Indicators
from market_analyzer.market_state import MarketState


@dataclass(frozen=True)
class ScoreResult:
    score: float
    strength: str
    confirmation_mode: str


class Scorer:

    @staticmethod
    def score_breakout_setup(
        features: dict,
        indicators: Indicators,
        market_state: MarketState,
    ) -> int:
        f = SimpleNamespace(**features)
        score = 0

        if f.breakout_strength_pct >= 0.008:
            score += 25
        elif f.breakout_strength_pct >= 0.006:
            score += 20
        elif f.breakout_strength_pct >= 0.004:
            score += 15

        if indicators.volume_ratio is not None:
            if indicators.volume_ratio >= 1.50:
                score += 20
            elif indicators.volume_ratio >= 1.25:
                score += 10

        if indicators.rsi is not None:
            if indicators.rsi >= 65:
                score += 15
            elif indicators.rsi >= 60:
                score += 10
            elif indicators.rsi >= 55:
                score += 5

        if indicators.ema_slope is not None:
            if indicators.ema_slope >= 0.003:
                score += 15
            elif indicators.ema_slope >= 0.002:
                score += 10
            elif indicators.ema_slope >= 0.001:
                score += 5

        if f.candle_body_ratio >= 0.8:
            score += 10
        elif f.candle_body_ratio >= 0.6:
            score += 5

        if market_state.structure.value in ("HHHL", "LHLL"):
            score += 5

        if market_state.trend_aligned:
            score += 5

        return min(score, 100)