from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

MAX_RISK_MULTIPLIERS = {
    BREAKOUT: {
        "A+": 2.50,
        "A": 1.80,
    },
    PULLBACK: {
        "A+": 2.0,
        "A": 1.50,
    },
    BREAKOUT_RETEST: {
        "A+": 1.50,
        "A": 1.00,
    },
    "liquidity_sweep_reversal": {
        "A+": 1.30,
        "A": 1.30,
    },
}

SETUP_RISK_MULTIPLIERS = {
    BREAKOUT: 1.5,
    BREAKOUT_RETEST: 1.0,
    "trend_pullback": 1.3,
    "liquidity_sweep_reversal": 1.3,
}

GRADE_RISK_MULTIPLIERS = {
    "A+": 1.3,
    "A": 1.0
}