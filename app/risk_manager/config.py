from __future__ import annotations

from app.core.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK
from app.core.types import MarketRegime

SETUP_RISK_MULTIPLIERS = {
    BREAKOUT : 1.0,
    BREAKOUT_RETEST: 0.5,
    PULLBACK: 0.5
}

GRADE_RISK_MULTIPLIERS = {
    "A+": 10.0,
    "A": 3.0,
    "SKIP" : 1.0
}

REGIME_RISK_MULTIPLIERS = {
    # Bullish
    MarketRegime.STRONG_BULLISH: 3.0,
    MarketRegime.BULLISH:        1.0,
    MarketRegime.WEAK_BULLISH:   0.5,

    # Neutral
    MarketRegime.RANGE:          0.5,
    MarketRegime.HIGH_VOLATILITY_CHOP: 0.5,

    # Bearish
    MarketRegime.STRONG_BEARISH: 3.0,
    MarketRegime.BEARISH:        1.0,
    MarketRegime.WEAK_BEARISH:   0.5,
}