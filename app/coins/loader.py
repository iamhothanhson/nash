from __future__ import annotations

import copy
from typing import Any, TypedDict

from coins import fet as fet_coin
from coins import render as render_coin
from coins import tao as tao_coin

class CoinConfigDict(TypedDict, total=False):
    min_risk_reward_multiple: float
    enforce_min_risk_reward_multiple: bool
    min_setup_score: int
    min_setup_score_a_plus: int
    pullback_min_setup_score: int
    pullback_min_setup_score_a_plus: int
    allowed_grades: list[str]
    confirmation_modes: list[str]
    partial_close: list[float]
    min_body: float
    max_opened_positions: int
    max_breakout_retest_position: int
    volatility_threshold: float
    bars_since_last_close: int
    price_rounding_decimal: int
    price_rounding_decimal_from_exchange: bool
    tp1_stop_buffer_percent: float
    atr_multiplier: float
    max_tp1_distance: float
    max_tp1_pct: float
    max_tp2_distance: float
    max_tp2_pct: float
    structure_tp1_when_above_pct: float
    use_structure_tp: bool
    tp_structure_lookback_15m: int
    tp_structure_min_separation_pct: int
    min_ema_slope: float
    risk_multiplier: float
_COIN_MODULES: dict[str, Any] = {
    "TAOUSDT": tao_coin,
    "RENDERUSDT": render_coin,
    "FETUSDT": fet_coin,
}

def normalize_coin_symbol(symbol: str) -> str:
    """Normalize e.g. SOL/USDT, SOL, SOLUSDT → SOLUSDT."""
    s = symbol.strip().upper().replace("/", "")
    if not s.endswith("USDT"):
        s = f"{s}USDT"
    return s
def _config_dict_for_module(mod: Any, sym: str) -> dict[str, Any]:
    symbol_key = sym.replace("USDT", "")
    cfg = getattr(mod, f"{symbol_key}_CONFIG", None)
    if not isinstance(cfg, dict):
        cfg = getattr(mod, "OVERRIDES", None)
    if not isinstance(cfg, dict):
        raise ValueError(f"Coin module for {sym} has no {symbol_key}_CONFIG dict")
    merged = copy.deepcopy(cfg)
    partial_close = getattr(mod, "PARTIAL_CLOSE", None)
    if isinstance(partial_close, (list, tuple)) and len(partial_close) == 3:
        merged["partial_close"] = [float(x) for x in partial_close]
    return merged

def get_coin_config(symbol: str | None) -> dict[str, Any]:
    """Return the registered per-coin config dict (no shared base merge)."""
    if not symbol or not str(symbol).strip():
        raise ValueError("get_coin_config requires a symbol")
    sym = normalize_coin_symbol(str(symbol))
    mod = _COIN_MODULES.get(sym)
    if mod is None:
        raise ValueError(f"No coin config registered for {sym}")
    return _config_dict_for_module(mod, sym)

def register_coin_module(symbol_usdt: str, module: Any) -> None:
    """Register extra coin overrides at runtime (e.g. for scaling past static files)."""
    _COIN_MODULES[normalize_coin_symbol(symbol_usdt)] = module
