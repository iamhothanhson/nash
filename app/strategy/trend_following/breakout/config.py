from app.core.types import MarketRegime


BREAKOUT_LONG_HARD = {
    "close_above_recent_high": True,
    "min_strength": 0.4,
    "require_ema_alignment": True,
    # Avoid ranging markets
    "min_adx": 20,
    "min_adx_1h": 20,
}

BREAKOUT_LONG_SOFT = {
    # Participation
    "min_volume_ratio": 1.2,

    # Trend must already be pointing up
    "min_ema_slope": 0.001,

    # Momentum confirmation
    "min_rsi": 55.0,

    # Strong bullish candle
    "min_body_ratio": 0.55,

    # Close near the high (little upper wick)
    "max_close_to_high_pct": 0.35,
}

BREAKOUT_SHORT_HARD = {
    "close_below_recent_low": True,
    "min_strength": 0.4,
    "require_ema_alignment": True,
    # Avoid ranging markets
    "min_adx": 20,
    "min_adx_1h": 20,
}

BREAKOUT_SHORT_SOFT = {
    # Strong market participation
    "min_volume_ratio": 1.2,

    # EMA must slope downward
    "max_ema_slope": -0.001,

    # Bearish momentum confirmation
    "max_rsi": 45.0,

    # Strong bearish candle body
    "min_body_ratio": 0.55,

    # Close near candle low
    "max_close_to_low_pct": 0.35,
}


BREAKOUT_ALLOWED_REGIMES = {
    MarketRegime.WEAK_BULLISH,
    MarketRegime.BULLISH,
    MarketRegime.STRONG_BULLISH
}