from __future__ import annotations
from typing import Any
from turtle import pd

from app.core.config import BREAKOUT_CONFIG
from app.core.constants import BREAKOUT
from app.setup_builder.config import SCORE_A
from core.enums import RejectReason
from market_analyzer.market_state import MarketState
from setup_builder.models import Direction, Setup, SetupType
from setup_builder.grader import Grader
from setup_builder.scorer import Scorer
from strategy.models import SetupCandidate


class SetupBuilder:

    @classmethod
    def build_from_candidate(
        cls,
        candidate: SetupCandidate,
        market_state: MarketState,
        reject_stats: Any = None,
        pipeline_stats: Any = None,
    ) -> Setup:
        data_15m = market_state.data_15m

        if data_15m is None or data_15m.empty:
            if pipeline_stats:
                pipeline_stats.setup_skip_no_data += 1
            return None

        entry = cls._compute_entry(
            data_15m=data_15m,
        )

        if entry is None:
            if pipeline_stats:
                pipeline_stats.setup_skip_no_entry += 1
            return None

        if candidate.setup_type == BREAKOUT:
            scorer = Scorer()
            score = scorer.score_breakout_setup(
                features=candidate.features,
                indicators=market_state.indicators,
                market_state=market_state,
                side=candidate.direction,
            )
        else:
            score = 0

        if score < SCORE_A:
            if reject_stats:
                reject_stats.reject(RejectReason.SCORE)
            if pipeline_stats:
                pipeline_stats.setup_skip_score += 1
                pipeline_stats.setup_skip_score_values.append(score)
            return None

        grade_result = Grader.grade(score)

        if pipeline_stats:
            pipeline_stats.setup_built += 1

        config = BREAKOUT_CONFIG if candidate.setup_type == BREAKOUT else {}

        return Setup(
            symbol=market_state.symbol,
            entry=entry,
            timestamp=market_state.timestamp,
            setup_type=SetupType(candidate.setup_type),
            side=Direction(candidate.direction),
            score=score,
            grade=grade_result.grade,
            market_state=market_state,
            features=candidate.features,
            config=config,
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
