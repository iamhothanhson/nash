from __future__ import annotations
from turtle import pd

from config.constants import BREAKOUT, MIN_SETUP_SCORE
from market_analyzer.market_state import MarketState
from setup_builder.config import Grade as GradeMap
from setup_builder.models import Direction, Setup, SetupType
from setup_builder.scorer import Scorer
from strategy.models import SetupCandidate


class SetupBuilder:

    @classmethod
    def build_from_candidate(
        cls,
        candidate: SetupCandidate,
        market_state: MarketState,
    ) -> Setup:
        data_15m = market_state.data_15m

        if data_15m is None or data_15m.empty:
            return None

        entry = cls._compute_entry(
            data_15m=data_15m,
        )

        if entry is None:
            return None

        if candidate.setup_type == BREAKOUT:
            score = Scorer.score_breakout_setup(
                features=candidate.features,
                indicators=market_state.indicators,
                market_state=market_state,
                side=candidate.direction,
            )
        else:
            score = 0

        if score < MIN_SETUP_SCORE:
            return None

        return Setup(
            symbol=market_state.symbol,
            entry=entry,
            timestamp=market_state.timestamp,
            setup_type=SetupType(candidate.setup_type),
            side=Direction(candidate.direction),
            score=score,
            market_state=market_state,
            features=candidate.features,
            anchor=candidate.anchor,
        )

    @staticmethod
    def _compute_entry(
        data_15m: pd.DataFrame,
    ) -> float | None:
        confirmation_candle = data_15m.iloc[-1]
        entry = float(confirmation_candle["close"])

        if entry <= 0:
            return None

        return entry
