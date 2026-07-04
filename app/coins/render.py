from __future__ import annotations

RENDER_CONFIG = {
    "min_risk_reward_multiple": 1.0,
    "min_setup_score": 8,
    "min_setup_score_a_plus": 11,
    "pullback_min_setup_score": 8,
    "pullback_min_setup_score_a_plus": 10,
    "allowed_grades": ["A+", "A"],
    "confirmation_modes": ["confirmed"],
    "min_body": 0.003,
    "partial_close": [0.50, 0.30, 0.20],
    "risk_multiplier": 1.0,
    "max_opened_positions": 1,
    "max_breakout_retest_position": 1,
    "min_ema_slope": 0.0,
    "price_rounding_decimal": 3,
    "bars_since_last_close": 6,
}
