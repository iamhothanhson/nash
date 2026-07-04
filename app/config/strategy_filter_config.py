BREAKOUT_FILTER_THRESHOLDS = {
    "enabled": False,
    "min_regime_confidence": 75,
    "min_adx_15m": 25.0,
    "min_volume_ratio": 1.25,
    "min_breakout_strength": 0.0050,
    "min_body_ratio": 0.60,
    "require_trend_alignment": True
}

SWEEP_FILTER_THRESHOLDS = {
    "enabled": False,
    "sweep_min_regime_confidence": 50,
    "sweep_min_volume_ratio": 0.80,
    "sweep_min_rejection_body_ratio": 0.50,
    "sweep_min_wick_ratio": 0.45,
    "sweep_max_rsi_long": 55.0,
    "sweep_min_rsi_short": 45.0,
    "require_trend_alignment": True
}
