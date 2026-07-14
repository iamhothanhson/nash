BREAKOUT_LONG_HARD = {
    "close_above_recent_high": True,
    "min_strength": 0.004,
    "require_ema_alignment": True,
}

BREAKOUT_LONG_SOFT = {
    "min_volume_ratio": 1.0,
    "min_ema_slope": 0.0,
    "min_rsi": 50.0,
    "min_body_ratio": 0.4,
    "max_close_to_high_pct": 0.3,
}

BREAKOUT_SHORT_HARD = {
    "close_below_recent_low": True,
    "min_strength": 0.004,
    "require_ema_alignment": True,
}

BREAKOUT_SHORT_SOFT = {
    "min_volume_ratio": 1.0,
    "max_ema_slope": 0.0,
    "max_rsi": 50.0,
    "min_body_ratio": 0.4,
    "max_close_to_low_pct": 0.3,
}
