from __future__ import annotations

TAO_CONFIG = {
    "min_risk_reward_multiple": 1.0,
    "min_setup_score": 8,
    "min_setup_score_a_plus": 11,
    "allowed_grades": ["A+", "A"],
    "confirmation_modes": ["confirmed", "strong"],
    "min_body": 0.002,
    "partial_close": [0.50, 0.30, 0.20],
    "risk_multiplier": 1.15,
    "max_opened_positions": 1,
    "max_breakout_retest_position": 1,
    "volatility_threshold": 0.004,
    "bars_since_last_close": 6,
    "price_rounding_decimal": 2,
    "trend_breakout_score_bonus": 3,
    "trend_pullback_min_setup_score": 7,
    "trend_pullback_min_setup_score_a_plus": 10,
}
