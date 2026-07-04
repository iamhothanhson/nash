from __future__ import annotations

from strategy.trend_following.config import (
    BREAKOUT_EMA_SLOPE_MIN,
    TREND_BREAKOUT_RETEST_LONG_RSI_MIN,
    TREND_BREAKOUT_RETEST_MAX_LEVEL_DEV,
    TREND_BREAKOUT_RETEST_MIN_BODY_RATIO,
    TREND_BREAKOUT_RETEST_MIN_RECLAIM_PCT,
    TREND_BREAKOUT_RETEST_MIN_VOL_RATIO,
    TREND_BREAKOUT_RETEST_SHORT_RSI_MAX,
)
from config.constants import BREAKOUT_RETEST
from strategy.trend_following.types import SetupCandidate


class BreakoutRetestDetector:
    retest_long = staticmethod(lambda market_state: BreakoutRetestDetector.detect_long(market_state))
    retest_short = staticmethod(lambda market_state: BreakoutRetestDetector.detect_short(market_state))

    @staticmethod
    def detect_long(market_state) -> SetupCandidate | None:
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        rf = features.retest
        ind = market_state.indicators or {}

        if not rf.bullish_retest_confirm:
            return None
        if not rf.touched_breakout_level:
            return None
        if not rf.retest_rejection_long:
            return None

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi_raw = ind.get("rsi_15m", 0.0)
        rsi = float(rsi_raw.iloc[-1]) if hasattr(rsi_raw, "iloc") else float(rsi_raw)
        max_dev = float(TREND_BREAKOUT_RETEST_MAX_LEVEL_DEV)
        min_reclaim = float(TREND_BREAKOUT_RETEST_MIN_RECLAIM_PCT)

        within_dev = rf.distance_from_breakout_level_pct <= max_dev
        reclaim_ok = rf.distance_from_breakout_level_pct >= min_reclaim

        if (
            ema_slope > (BREAKOUT_EMA_SLOPE_MIN * 0.0)
            and rsi > TREND_BREAKOUT_RETEST_LONG_RSI_MIN
            and rf.body_ratio >= float(TREND_BREAKOUT_RETEST_MIN_BODY_RATIO)
            and rf.close_strength >= 0.40
            and rf.vol_ratio >= float(TREND_BREAKOUT_RETEST_MIN_VOL_RATIO)
            and within_dev
            and reclaim_ok
        ):
            return SetupCandidate(
                setup_type=BREAKOUT_RETEST,
                direction="LONG",
                anchor=float(rf.breakout_level),
                setup_points=0,
                key_level_points=0,
                confirmation_points=0,
                raw_score=0.0,
                trigger_type="breakout_retest_long",
                confidence=0.0,
                debug_reason=(
                    f"level={rf.breakout_level:.6f},"
                    f"body_ratio={rf.body_ratio:.3f},"
                    f"close_strength={rf.close_strength:.3f},"
                    f"vol_ratio={rf.vol_ratio:.3f}"
                ),
            )
        return None

    @staticmethod
    def detect_short(market_state) -> SetupCandidate | None:
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        rf = features.retest
        ind = market_state.indicators or {}

        if not rf.bearish_retest_confirm:
            return None
        if not rf.touched_breakout_level:
            return None
        if not rf.retest_rejection_short:
            return None

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi_raw = ind.get("rsi_15m", 0.0)
        rsi = float(rsi_raw.iloc[-1]) if hasattr(rsi_raw, "iloc") else float(rsi_raw)
        max_dev = float(TREND_BREAKOUT_RETEST_MAX_LEVEL_DEV)
        min_reclaim = float(TREND_BREAKOUT_RETEST_MIN_RECLAIM_PCT)

        within_dev = rf.distance_from_breakout_level_pct <= max_dev
        reclaim_ok = rf.distance_from_breakout_level_pct >= min_reclaim

        if (
            ema_slope < -(BREAKOUT_EMA_SLOPE_MIN * 0.0)
            and rsi < TREND_BREAKOUT_RETEST_SHORT_RSI_MAX
            and rf.body_ratio >= float(TREND_BREAKOUT_RETEST_MIN_BODY_RATIO)
            and rf.close_strength >= 0.40
            and rf.vol_ratio >= float(TREND_BREAKOUT_RETEST_MIN_VOL_RATIO)
            and within_dev
            and reclaim_ok
        ):
            return SetupCandidate(
                setup_type=BREAKOUT_RETEST,
                direction="SHORT",
                anchor=float(rf.breakout_level),
                setup_points=0,
                key_level_points=0,
                confirmation_points=0,
                raw_score=0.0,
                trigger_type="breakout_retest_short",
                confidence=0.0,
                debug_reason=(
                    f"level={rf.breakout_level:.6f},"
                    f"body_ratio={rf.body_ratio:.3f},"
                    f"close_strength={rf.close_strength:.3f},"
                    f"vol_ratio={rf.vol_ratio:.3f}"
                ),
            )
        return None
