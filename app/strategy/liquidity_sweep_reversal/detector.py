from __future__ import annotations

from strategy.liquidity_sweep_reversal.config import (
    LIQUIDITY_AVOID_COUNTER_TREND_ENABLED,
    LIQUIDITY_COUNTER_TREND_EMA_SPREAD_MIN,
    LIQUIDITY_COUNTER_TREND_SLOPE_MIN_FRAC,
    LIQUIDITY_MIN_Q,
    LIQUIDITY_SHORT_NEAR_SWING_LOW_MAX_PCT,
    LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED,
    SLOPE_THRESHOLD,
    VOLATILITY_THRESHOLD,
)
from config.constants import LIQUIDITY_SWEEP
from strategy.models import SetupCandidate


class LiquiditySweepDetector:
    """Detect liquidity sweep reversal setups from market_state features + indicators."""

    sweep_long = staticmethod(lambda market_state: LiquiditySweepDetector.detect_long(market_state))
    sweep_short = staticmethod(lambda market_state: LiquiditySweepDetector.detect_short(market_state))

    MIN_WICK_RATIO: float = 0.45
    MIN_BODY_RATIO: float = 0.30
    MIN_VOL_RATIO: float = 0.80

    @staticmethod
    def detect_long(market_state) -> SetupCandidate | None:
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        sf = features.sweep
        ind = market_state.indicators or {}

        if not sf.swept_low:
            return None
        if not sf.reclaimed_after_low_sweep:
            return None
        if not sf.rejection_long:
            return None

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi = float(ind.get("rsi_15m", 0.0))
        vol_ratio = sf.volume_ratio

        if ema_slope < SLOPE_THRESHOLD:
            return None
        if rsi < 30 or rsi > 75:
            return None
        if vol_ratio < LiquiditySweepDetector.MIN_VOL_RATIO:
            return None
        if sf.lower_wick_ratio < LiquiditySweepDetector.MIN_WICK_RATIO:
            return None

        if LIQUIDITY_AVOID_COUNTER_TREND_ENABLED:
            ema_spread = float(ind.get("ema20_slope_1h", 0.0))
            if ema_spread < -LIQUIDITY_COUNTER_TREND_EMA_SPREAD_MIN:
                return None

        return SetupCandidate(
            setup_type=LIQUIDITY_SWEEP,
            direction="LONG",
            anchor=float(sf.swing_low),
            setup_points=0,
            key_level_points=0,
            confirmation_points=0,
            raw_score=0.0,
            trigger_type="liquidity_sweep_long",
            confidence=0.0,
            debug_reason=(
                f"swing_low={sf.swing_low:.6f},"
                f"lower_wick_ratio={sf.lower_wick_ratio:.3f},"
                f"vol_ratio={vol_ratio:.3f}"
            ),
        )

    @staticmethod
    def detect_short(market_state) -> SetupCandidate | None:
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        sf = features.sweep
        ind = market_state.indicators or {}

        if not sf.swept_high:
            return None
        if not sf.reclaimed_after_high_sweep:
            return None
        if not sf.rejection_short:
            return None

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi = float(ind.get("rsi_15m", 0.0))
        vol_ratio = sf.volume_ratio

        if ema_slope > -SLOPE_THRESHOLD:
            return None
        if rsi < 25 or rsi > 70:
            return None
        if vol_ratio < LiquiditySweepDetector.MIN_VOL_RATIO:
            return None
        if sf.upper_wick_ratio < LiquiditySweepDetector.MIN_WICK_RATIO:
            return None

        if LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED:
            if ema_slope > 0:
                return None

        if LIQUIDITY_AVOID_COUNTER_TREND_ENABLED:
            ema_spread = float(ind.get("ema20_slope_1h", 0.0))
            if ema_spread > LIQUIDITY_COUNTER_TREND_EMA_SPREAD_MIN:
                return None

        return SetupCandidate(
            setup_type=LIQUIDITY_SWEEP,
            direction="SHORT",
            anchor=float(sf.swing_high),
            setup_points=0,
            key_level_points=0,
            confirmation_points=0,
            raw_score=0.0,
            trigger_type="liquidity_sweep_short",
            confidence=0.0,
            debug_reason=(
                f"swing_high={sf.swing_high:.6f},"
                f"upper_wick_ratio={sf.upper_wick_ratio:.3f},"
                f"vol_ratio={vol_ratio:.3f}"
            ),
        )

    @classmethod
    def detect(cls, market_state) -> SetupCandidate | None:
        return cls.detect_long(market_state) or cls.detect_short(market_state)
