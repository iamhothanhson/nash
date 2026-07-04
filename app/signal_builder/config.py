from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

MAX_TP_CONFIG = {
    BREAKOUT: {
        "max_tp1_pct": 1.4,
        "max_tp2_pct": 2.8
    },
    BREAKOUT_RETEST: {
        "max_tp1_pct": 1.2,
        "max_tp2_pct": 2.4
    },
    PULLBACK: {
        "max_tp1_pct": 1.0,
        "max_tp2_pct": 2.0
    },
    "liquidity_sweep_reversal": {
        "max_tp1_pct": 0.8,
        "max_tp2_pct": 1.6
    }
}

TP_CONFIG = {
    "tp1_r": 1.0,
    "tp2_r": 1.5,
    # TP1 stop-to-breakeven
    "tp1_stop_buffer_percent": 0.1,
    # TP3 structure trailing
    "tp3_structure_pivot_bars": 2,
    "tp3_structure_lookback_15m": 96,
    "tp3_structure_trail_atr_period": 14,
    "tp3_structure_trail_atr_multiplier":  0.20
}