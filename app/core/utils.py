from __future__ import annotations

from typing import Any

from config.constants import LIQUIDITY_SWEEP_REVERSAL, TREND_FOLLOWING
from coins.loader import get_coin_config


TREND_FOLLOWING_SETUPS = frozenset({"breakout", "breakout_retest", "pullback"})

def dynamic_strength_threshold(atr_pct: float, config: dict[str, Any]) -> float:
    return max(config["min_strength"], atr_pct * config["min_strength_atr_factor"])


def resolve_strategy_family(setup_type: str) -> str:
    return TREND_FOLLOWING if setup_type in TREND_FOLLOWING_SETUPS else LIQUIDITY_SWEEP_REVERSAL


def round_price(symbol: str | None, value: float) -> float:
    cfg = get_coin_config(symbol)
    raw = cfg.get("price_rounding_decimal")
    if raw is not None:
        try:
            return round(float(value), max(0, min(16, int(raw))))
        except (TypeError, ValueError):
            pass
    return round(float(value), 4)


def resolve_pct(val: float | None) -> float:
    if val is None:
        return 0.0
    return max(0.0, float(val) / 100.0)

