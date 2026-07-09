from typing import Any

def dynamic_strength_threshold(atr_pct: float, config: dict[str, Any]) -> float:
    return max(config["min_strength"], atr_pct * config["min_strength_atr_factor"])