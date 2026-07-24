from dataclasses import dataclass
from types import SimpleNamespace

from app.core.types import MarketStructure
from indicators.models import Indicators
from market_analyzer.market_state import MarketState


@dataclass(frozen=True)
class ScoreResult:
    score: float


class Scorer:
    @staticmethod
    def score_breakout_setup(
        features: dict,
        indicators: Indicators,
        market_state: MarketState,
        side: str,
    ) -> int:
        f = SimpleNamespace(**features)
        score = 0

        # Breakout Strength (25)
        if f.breakout_strength_pct >= 0.008:
            score += 25
        elif f.breakout_strength_pct >= 0.006:
            score += 20
        elif f.breakout_strength_pct >= 0.004:
            score += 15
        elif f.breakout_strength_pct >= 0.003:
            score += 10
        elif f.breakout_strength_pct >= 0.002:
            score += 5

        # Volume (20)
        if indicators.volume_ratio >= 2.0:
            score += 20
        elif indicators.volume_ratio >= 1.5:
            score += 15
        elif indicators.volume_ratio >= 1.2:
            score += 10
        elif indicators.volume_ratio >= 1.0:
            score += 5

        # RSI (15)
        if 60 <= indicators.rsi <= 68:
            score += 15
        elif 55 <= indicators.rsi < 60:
            score += 10
        elif 68 < indicators.rsi <= 72:
            score += 5

        # EMA Slope (15)
        if indicators.ema_slope >= 0.003:
            score += 15
        elif indicators.ema_slope >= 0.002:
            score += 10
        elif indicators.ema_slope >= 0.001:
            score += 5

        # Candle Body (10)
        if f.candle_body_ratio >= 0.80:
            score += 10
        elif f.candle_body_ratio >= 0.60:
            score += 5

        # Market Structure (5)
        if side == "LONG" and market_state.structure == MarketStructure.HHHL:
            score += 5

        if side == "SHORT" and market_state.structure == MarketStructure.LHLL:
            score += 5

        # Trend Alignment (5)
        if market_state.trend_aligned:
            score += 5

        # HTF Confirmation (5)
        if f.htf_confirmed:
            score += 5

        return min(score, 100)