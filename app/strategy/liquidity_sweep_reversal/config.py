from __future__ import annotations

# Liquidity sweep reversal strategy parameters (code defaults; not loaded from .env).

MAX_SL_DISTANCE: float = 0.02
SLOPE_THRESHOLD: float = 0.002
VOLATILITY_THRESHOLD: float = 0.0040
ATR_PERIOD: int = 14
ATR_MULTIPLIER: float = 1.0  # multiplies ATR for stop distance
STOP_ATR_MULT: float = 1.10
RISK_MULTIPLIER: float = 1.0  # multiplies risk per trade

# TP3 = 15m structure runner (see settings.TP1_R / TP2_R).
# 5m history window for liquidity signal scan (bars).
LIQUIDITY_LOOKBACK_5M: int = 288
LIQUIDITY_MIN_Q: float = 0.18

# TP3 structure snap on 15m swings beyond TP2.
LIQUIDITY_TP_STRUCTURE_LOOKBACK_15M: int = 96
# Min separation between structure levels: integer hundredths of a percent (15 = 0.15%).
LIQUIDITY_TP_STRUCTURE_MIN_SEPARATION_PCT: int = 15

# Avoid fading clear 1H trend: UP blocks SHORT, DOWN blocks LONG.
LIQUIDITY_AVOID_COUNTER_TREND_ENABLED: bool = True
LIQUIDITY_COUNTER_TREND_EMA_SPREAD_MIN: float = 0.001
LIQUIDITY_COUNTER_TREND_SLOPE_MIN_FRAC: float = 0.0005

# Block liquidity SHORT when 15m is recovering (price above EMA20 with rising slope).
LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED: bool = True
LIQUIDITY_SHORT_RECOVERY_SLOPE_BARS: int = 5

# Block liquidity SHORT when entry is still near a recent 15m/1H swing low (V-reversal zone).
LIQUIDITY_SHORT_NEAR_SWING_LOW_ENABLED: bool = True
LIQUIDITY_SHORT_NEAR_SWING_LOW_LOOKBACK_15M: int = 96
LIQUIDITY_SHORT_NEAR_SWING_LOW_LOOKBACK_1H: int = 48
# Percent points from entry to swing low (8 = within 8% above the low).
LIQUIDITY_SHORT_NEAR_SWING_LOW_MAX_PCT: int = 8