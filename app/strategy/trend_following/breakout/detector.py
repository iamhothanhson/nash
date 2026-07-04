from __future__ import annotations

from strategy.trend_following.config import (
    BREAKOUT_EMA_SLOPE_MIN,
    BREAKOUT_LONG_RSI_MIN,
    BREAKOUT_MIN_STRENGTH,
    BREAKOUT_MIN_VOL_RATIO,
    BREAKOUT_SHORT_RSI_MAX,
)
from config.constants import BREAKOUT
from strategy.trend_following.types import SetupCandidate


class BreakoutDetector:
    breakout_long = staticmethod(lambda market_state: BreakoutDetector().breakout_long_candidate(market_state))
    breakout_short = staticmethod(lambda market_state: BreakoutDetector().breakout_short_candidate(market_state))

    def breakout_long_candidate(self, market_state):
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        bf = features.breakout
        ind = market_state.indicators or {}

        if not bf.close_above_recent_high:
            return None

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi_raw = ind.get("rsi_15m", 0.0)
        rsi = float(rsi_raw.iloc[-1]) if hasattr(rsi_raw, "iloc") else float(rsi_raw)
        min_breakout = float(BREAKOUT_MIN_STRENGTH)

        if (
            ema_slope > BREAKOUT_EMA_SLOPE_MIN
            and rsi > BREAKOUT_LONG_RSI_MIN
            and bf.breakout_strength > min_breakout
            and bf.volume_ratio >= float(BREAKOUT_MIN_VOL_RATIO)
        ):
            return SetupCandidate(
                setup_type=BREAKOUT,
                direction="LONG",
                anchor=float(bf.recent_high_7),
                key_level_points=0,
                confirmation_points=0,
                trigger_type="breakout_long",
                confidence=0.0,
                debug_reason=(
                    f"strength={bf.breakout_strength:.6f},"
                    f"vol_ratio={bf.volume_ratio:.3f}"
                ),
            )
        return None

    def breakout_short_candidate(self, market_state):
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        bf = features.breakout
        ind = market_state.indicators or {}

        if not bf.close_below_recent_low:
            return None

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi_raw = ind.get("rsi_15m", 0.0)
        rsi = float(rsi_raw.iloc[-1]) if hasattr(rsi_raw, "iloc") else float(rsi_raw)
        min_breakout = float(BREAKOUT_MIN_STRENGTH)

        if (
            ema_slope < -BREAKOUT_EMA_SLOPE_MIN
            and rsi < BREAKOUT_SHORT_RSI_MAX
            and bf.breakout_strength > min_breakout
            and bf.volume_ratio >= float(BREAKOUT_MIN_VOL_RATIO)
        ):
            return SetupCandidate(
                setup_type=BREAKOUT,
                direction="SHORT",
                anchor=float(bf.recent_low_7),
                key_level_points=0,
                confirmation_points=0,
                trigger_type="breakout_short",
                confidence=0.0,
                debug_reason=(
                    f"strength={bf.breakout_strength:.6f},"
                    f"vol_ratio={bf.volume_ratio:.3f}"
                ),
            )
        return None
