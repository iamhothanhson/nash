from __future__ import annotations

from market_analyzer.market_state import MarketState
from setup_builder.config import Grade as GradeMap
from setup_builder.models import Setup
from strategy.models import SetupCandidate

class SetupBuilder:

    @classmethod
    def build_from_candidate(
        cls,
        candidate: SetupCandidate,
        market_state: MarketState,
        score: float,
    ) -> Setup:

        return Setup(
            symbol=market_state.symbol,
            timestamp=getattr(market_state, "timestamp", 0),
            setup_type=candidate.setup_type,
            side=candidate.direction,
            grade=GradeMap["Skip"],
            score=score,
            market_state=market_state,
        )
