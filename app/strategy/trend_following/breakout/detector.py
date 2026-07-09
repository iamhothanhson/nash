from __future__ import annotations

from common.utils import dynamic_strength_threshold
from config.constants import BREAKOUT
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT


def check_breakout_long(bf, cfg: dict) -> bool:
    strength_threshold = dynamic_strength_threshold(bf.atr_percent, cfg)
    return (
        bf.close_above_recent_high
        and bf.breakout_strength >= strength_threshold
        and bf.volume_ratio >= cfg["min_volume_ratio"]
        and bf.ema_slope >= cfg["min_ema_slope"]
        and bf.rsi >= cfg["min_rsi"]
        and bf.body_ratio >= cfg["min_body_ratio"]
        and bf.close_to_high_pct <= cfg["max_close_to_high_pct"]
        and (
            not cfg["require_ema_alignment"]
            or bf.ema_bullish_alignment
        )
    )


def check_breakout_short(bf, cfg: dict) -> bool:
    strength_threshold = dynamic_strength_threshold(bf.atr_percent, cfg)
    return (
        bf.close_below_recent_low
        and bf.breakout_strength >= strength_threshold
        and bf.volume_ratio >= cfg["min_volume_ratio"]
        and bf.ema_slope <= cfg["max_ema_slope"]
        and bf.rsi <= cfg["max_rsi"]
        and bf.body_ratio >= cfg["min_body_ratio"]
        and bf.close_to_low_pct <= cfg["max_close_to_low_pct"]
        and (
            not cfg["require_ema_alignment"]
            or bf.ema_bearish_alignment
        )
    )

class BreakoutDetector:

    @staticmethod
    def _satisfies(market_state, cfg, check_fn) -> bool:
        features = getattr(market_state, "features", None)
        if features is None:
            return False
        return check_fn(features.breakout, cfg)

    def breakout_long_candidate(self, market_state):
        if not self._satisfies(market_state, BREAKOUT_LONG, check_breakout_long):
            return None
        bf = market_state.features.breakout
        return SetupCandidate(
            setup_type=BREAKOUT,
            direction="LONG",
            trigger_type="breakout",
            anchor=float(bf.recent_high_7),
            detected_at=market_state.timestamp,
            timeframe=market_state.timeframe,
            features={
                "breakout_strength": bf.breakout_strength,
                "breakout_level": bf.recent_high_7,
            },
        )

    def breakout_short_candidate(self, market_state):
        if not self._satisfies(market_state, BREAKOUT_SHORT, check_breakout_short):
            return None
        bf = market_state.features.breakout
        return SetupCandidate(
            setup_type=BREAKOUT,
            direction="SHORT",
            trigger_type="breakout",
            anchor=float(bf.recent_low_7),
            detected_at=market_state.timestamp,
            timeframe=market_state.timeframe,
            features={
                "breakout_strength": bf.breakout_strength,
                "breakout_level": bf.recent_low_7,
            },
        )
