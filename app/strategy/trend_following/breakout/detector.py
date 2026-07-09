from __future__ import annotations

from config.constants import BREAKOUT
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT

class BreakoutDetector:

    def breakout_long_candidate(self, market_state):
        SetupCandidate(
            setup_type=BREAKOUT,
            direction="LONG",
            trigger_type="breakout",
            # Key price levels
            anchor=float(bf.recent_high_7),
            # Setup metadata
            detected_at=market_state.timestamp,
            timeframe=market_state.timeframe,
            # Detector evidence
            metadata={
                "breakout_strength": bf.breakout_strength,
                "breakout_level": bf.recent_high_7,
            },
        )

    def breakout_short_candidate(self, market_state):
        SetupCandidate(
            setup_type=BREAKOUT,
            direction="SHORT",
            trigger_type="breakout",
            # Key price levels
            anchor=float(bf.recent_high_7),
            # Setup metadata
            detected_at=market_state.timestamp,
            timeframe=market_state.timeframe,
            # Detector evidence
            metadata={
                "breakout_strength": bf.breakout_strength,
                "breakout_level": bf.recent_high_7,
            }
        )
