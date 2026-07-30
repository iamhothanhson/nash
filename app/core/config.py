BREAKOUT_CONFIG = {
    "sl_atr_mult": 1.5,
    "tp1_rr": 2.0,
    "tp1_close_pct": 0.50,
    "tp2": {
        "type": "atr_trailing",
        "atr_mult": 2.0,
    },
    "min_sl_distance": 0.01,
    "max_sl_distance": 0.03
}

SETUP_CONFIGS: dict[str, dict] = {
    "breakout": BREAKOUT_CONFIG,
}

TP_CLOSE_PCT = {
    "tp_1": 40,
    "tp_2": 60
}

MAX_TP_CONFIG = {
    "breakout": {
        "max_tp1_pct": 1.5,
        "max_tp2_pct": 2.5
    }
}