BREAKOUT_LONG = {
    "close_above_recent_high": True,
    "min_strength": 0.004,
    "min_strength_atr_factor": 0.3,
    "min_volume_ratio": 1.25,
    "min_ema_slope": 0.001,
    "min_rsi": 55.0,

    # Quality filters
    "min_body_ratio": 0.6,
    "max_close_to_high_pct": 0.2,
    "require_ema_alignment": True,

    # Trade filters
    "min_sl_distance": 0.003,
}

BREAKOUT_SHORT = {
    "close_below_recent_low": True,
    "min_strength": 0.004,
    "min_strength_atr_factor": 0.3,
    "min_volume_ratio": 1.25,
    "max_ema_slope": -0.001,
    "max_rsi": 45.0,

    # Quality filters
    "min_body_ratio": 0.6,
    "max_close_to_low_pct": 0.2,
    "require_ema_alignment": True,

    # Trade filters
    "min_sl_distance": 0.003,
}

