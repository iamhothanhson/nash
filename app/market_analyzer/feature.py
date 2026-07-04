from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BreakoutFeatures:
    # Structure levels
    recent_high_7: float = 0.0
    recent_low_7: float = 0.0
    recent_high_20: float = 0.0
    recent_low_20: float = 0.0

    # Breakout state
    breakout_up: bool = False
    breakout_down: bool = False
    close_above_recent_high: bool = False
    close_below_recent_low: bool = False

    # Strength
    breakout_strength: float = 0.0
    breakout_distance_pct: float = 0.0

    # Momentum
    momentum_up: bool = False
    momentum_down: bool = False

    # Volume
    volume_ratio: float = 0.0


@dataclass(frozen=True)
class PullbackFeatures:
    # EMA / zone
    price: float = 0.0
    ema_val: float = 0.0
    ema_deviation_pct: float = 0.0
    in_pullback_zone_long: bool = False
    in_pullback_zone_short: bool = False

    # Candle
    bullish_body: bool = False
    bearish_body: bool = False
    body_size: float = 0.0
    range_size: float = 0.0
    body_ratio: float = 0.0

    # Prior candle structure
    prior_high: float = 0.0
    prior_low: float = 0.0
    prior_mid: float = 0.0

    close_above_prior_high: bool = False
    close_below_prior_low: bool = False
    close_above_prior_mid: bool = False
    close_below_prior_mid: bool = False

    # Momentum / impulse
    momentum_up: bool = False
    momentum_down: bool = False
    impulse_pct: float = 0.0

    # Volume
    volume_ratio: float = 0.0

    # Final confirmation
    reclaim_long: bool = False
    reclaim_short: bool = False


@dataclass(frozen=True)
class SweepFeatures:
    # Swing levels
    swing_high: float = 0.0
    swing_low: float = 0.0

    # Sweep detection
    swept_high: bool = False
    swept_low: bool = False

    # Reclaim
    reclaimed_after_high_sweep: bool = False
    reclaimed_after_low_sweep: bool = False

    # Candle wick
    upper_wick: float = 0.0
    lower_wick: float = 0.0
    upper_wick_ratio: float = 0.0
    lower_wick_ratio: float = 0.0
    body_ratio: float = 0.0

    # Distance
    distance_from_swing_high_pct: float = 0.0
    distance_from_swing_low_pct: float = 0.0

    # Volume
    volume_ratio: float = 0.0

    # Final confirmation
    rejection_long: bool = False
    rejection_short: bool = False


@dataclass(frozen=True)
class RetestFeatures:
    # Breakout level
    breakout_level: float = 0.0
    distance_from_breakout_level_pct: float = 0.0

    # Touch / rejection
    touched_breakout_level: bool = False
    retest_rejection_long: bool = False
    retest_rejection_short: bool = False

    # Candle quality
    body_ratio: float = 0.0
    close_strength: float = 0.0
    vol_ratio: float = 0.0

    # Confirmation
    bullish_retest_confirm: bool = False
    bearish_retest_confirm: bool = False


@dataclass(frozen=True)
class SetupFeatures:
    breakout: BreakoutFeatures
    pullback: PullbackFeatures
    sweep: SweepFeatures
    retest: RetestFeatures

    @classmethod
    def empty(cls) -> "SetupFeatures":
        return cls(
            breakout=BreakoutFeatures(),
            pullback=PullbackFeatures(),
            sweep=SweepFeatures(),
            retest=RetestFeatures(),
        )