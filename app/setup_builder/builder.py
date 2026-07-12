from __future__ import annotations

from config.constants import BREAKOUT
from market_analyzer.market_state import MarketState
from setup_builder.config import Grade as GradeMap
from setup_builder.models import Setup
from setup_builder.scorer import Scorer
from strategy.models import SetupCandidate


class SetupBuilder:

    @classmethod
    def build_from_candidate(
        cls,
        candidate: SetupCandidate,
        market_state: MarketState,
    ) -> Setup:
        if candidate.setup_type == BREAKOUT:
            score = Scorer.score_breakout_setup(
                features=candidate.features,
                indicators=market_state.indicators,
                market_state=market_state,
            )
        else:
            score = 0

        return Setup(
            symbol=market_state.symbol,
            timestamp=market_state.timestamp,
            setup_type=candidate.setup_type,
            side=candidate.direction,
            score=score,
            market_state=market_state,
            features=candidate.features,
            anchor=candidate.anchor,
        )
