from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

MAX_TP_CONFIG = {
    BREAKOUT: {
        "max_tp1_pct": 1.5,
        "max_tp2_pct": 2.5
    },
    BREAKOUT_RETEST: {
        "max_tp1_pct": 1.0,
        "max_tp2_pct": 2.0
    },
    PULLBACK: {
        "max_tp1_pct": 1.0,
        "max_tp2_pct": 2.0
    }
}

TP_CONFIG = {
    "tp1_r": 1.0,
    "tp2_r": 1.5,
    # TP3 structure trailing
    "tp3_structure_pivot_bars": 2,
    "tp3_structure_lookback_15m": 96,
    "tp3_structure_trail_atr_period": 14,
    "tp3_structure_trail_atr_multiplier":  0.20
}