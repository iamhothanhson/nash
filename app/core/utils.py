from typing import Any

from config.constants import LIQUIDITY_SWEEP_REVERSAL, TREND_FOLLOWING
from signal_builder.config import MAX_TP_CONFIG

TREND_FOLLOWING_SETUPS = frozenset({"breakout", "breakout_retest", "pullback"})


def dynamic_strength_threshold(atr_pct: float, config: dict[str, Any]) -> float:
    return max(config["min_strength"], atr_pct * config["min_strength_atr_factor"])


def resolve_strategy_family(setup_type: str) -> str:
    return TREND_FOLLOWING if setup_type in TREND_FOLLOWING_SETUPS else LIQUIDITY_SWEEP_REVERSAL


def get_coin_config(symbol: str) -> dict[str, Any] | None:
    return None