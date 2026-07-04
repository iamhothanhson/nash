Grade: dict = {
    "A+": "A+",
    "A": "A",
    "Skip": "Skip",
}

A_PLUS_SETUP = {
    "market_structure_1h": "aligned",
    "market_structure_15m": "aligned",
    "regime_confidence": 90,
    "adx_15m": 30,
    "adx_1h": 25,
    "volume_ratio": 1.8,
    "atr_percentile": 50,
    "rsi_long_min": 60,
    "rsi_short_max": 40,
    "reward_space_rr": 2.5,
    "session": ["EU", "US"],
}

A_SETUP = {
    "market_structure_1h": "aligned",
    "market_structure_15m": "aligned",
    "regime_confidence": 80,
    "adx_15m": 25,
    "adx_1h": 20,
    "volume_ratio": 1.3,
    "atr_percentile": 30,
    "rsi_long_min": 55,
    "rsi_short_max": 45,
    "reward_space_rr": 2.0,
    "session": ["Asia", "EU", "US"],
}

MARKET_STRUCTURE = ("HHHL", "LHLL")
