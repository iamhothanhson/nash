from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

MAX_TP_CONFIG = {
    BREAKOUT: {
        "max_tp1_pct": 1.5,
        "max_tp2_pct": 2.5,
        "max_tp3_pct": 3.0
    },
    BREAKOUT_RETEST: {
       "max_tp1_pct": 0.8,
        "max_tp2_pct": 1.5,
        "max_tp3_pct": 2.5
    },
    PULLBACK: {
        "max_tp1_pct": 0.8,
        "max_tp2_pct": 1.5,
        "max_tp3_pct": 2.5
    }
}

TP_CONFIG = {
    "tp1_r": 1.0,
    "tp2_r": 1.5,
    "tp3_r": 2.0
}