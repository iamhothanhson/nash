from __future__ import annotations

import copy
import json
from typing import Any, TypedDict
from urllib.request import Request, urlopen

from coins import fet as fet_coin
from coins import render as render_coin
from coins import tao as tao_coin

from config.constants import BREAKOUT, BREAKOUT_RETEST, PULLBACK

_exchange_price_decimal_cache: dict[str, int] = {}

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


def resolve_atr_multiplier(cfg: dict[str, Any]) -> float:
    """
    Per-coin ATR scale for stop buffers.

    Returns ``cfg['atr_multiplier']`` when set, else liquidity default (1.0).
    """
    from strategy.liquidity_sweep_reversal.sweep_revesal_config import ATR_MULTIPLIER

    raw = cfg.get("atr_multiplier")
    if raw is not None:
        try:
            return max(0.0, float(raw))
        except (TypeError, ValueError):
            pass
    return float(ATR_MULTIPLIER)


def _resolve_max_tp_pct_distance(
    cfg: dict[str, Any],
    *,
    frac_key: str,
    pct_key: str,
) -> float | None:
    raw = cfg.get(frac_key)
    if raw is None:
        pct = cfg.get(pct_key)
        if pct is not None:
            try:
                return max(0.0, float(pct) / 100.0)
            except (TypeError, ValueError):
                return None
        return None
    try:
        v = float(raw)
        if v > 1.0:
            return max(0.0, v / 100.0)
        return max(0.0, v)
    except (TypeError, ValueError):
        return None


def resolve_max_tp1_distance(cfg: dict[str, Any]) -> float | None:
    """Per-coin max TP1 distance (``max_tp1_pct`` percent points, e.g. 2.5 = 2.5%)."""
    return _resolve_max_tp_pct_distance(cfg, frac_key="max_tp1_distance", pct_key="max_tp1_pct")


def resolve_max_tp2_distance(cfg: dict[str, Any]) -> float | None:
    """Per-coin max TP2 distance (``max_tp2_pct`` percent points, e.g. 3.5 = 3.5%)."""
    return _resolve_max_tp_pct_distance(cfg, frac_key="max_tp2_distance", pct_key="max_tp2_pct")


def coin_enforces_min_risk_reward(cfg: dict[str, Any]) -> bool:
    """When false, skip min_risk_reward_multiple at signal build and execution gates."""
    raw = cfg.get("enforce_min_risk_reward_multiple")
    if raw is None:
        return True
    return bool(raw)


def resolve_structure_tp1_min_distance(cfg: dict[str, Any]) -> float | None:
    """
    Use structure TP1 only when R-based TP1 distance exceeds this fraction.

    ``structure_tp1_when_above_pct``: percent points (2.5 = 2.5%).
    Falls back to ``max_tp1_pct`` when unset (same units).
    """
    raw = cfg.get("structure_tp1_when_above_pct")
    if raw is None:
        raw = cfg.get("max_tp1_pct")
    if raw is None:
        return None
    try:
        return max(0.0, float(raw) / 100.0)
    except (TypeError, ValueError):
        return None


def coin_uses_structure_tp(cfg: dict[str, Any]) -> bool:
    """When true, TP1/TP2 come from 15m swings (with R-multiple fallback)."""
    return bool(cfg.get("use_structure_tp") or cfg.get("tp1_use_structure"))


def resolve_tp_structure_lookback_15m(cfg: dict[str, Any]) -> int:
    from strategy.liquidity_sweep_reversal.sweep_revesal_config import (
        LIQUIDITY_TP_STRUCTURE_LOOKBACK_15M,
    )

    raw = cfg.get("tp_structure_lookback_15m")
    if raw is not None:
        try:
            return max(24, int(raw))
        except (TypeError, ValueError):
            pass
    return int(LIQUIDITY_TP_STRUCTURE_LOOKBACK_15M)


def resolve_tp_structure_sep_frac(cfg: dict[str, Any]) -> float:
    """
    Min swing separation as price fraction.

    ``tp_structure_min_separation_pct``: integer hundredths of a percent (15 = 0.15%).
    Legacy ``tp_structure_min_separation_frac`` still accepted.
    """
    from strategy.liquidity_sweep_reversal.sweep_revesal_config import (
        LIQUIDITY_TP_STRUCTURE_MIN_SEPARATION_PCT,
    )

    pct = cfg.get("tp_structure_min_separation_pct")
    if pct is not None:
        try:
            return max(0.0005, float(int(pct)) / 10000.0)
        except (TypeError, ValueError):
            pass
    raw = cfg.get("tp_structure_min_separation_frac")
    if raw is not None:
        try:
            return max(0.0005, float(raw))
        except (TypeError, ValueError):
            pass
    return max(0.0005, float(int(LIQUIDITY_TP_STRUCTURE_MIN_SEPARATION_PCT)) / 10000.0)


def scale_atr_stop_mult(base_mult: float, cfg: dict[str, Any]) -> float:
    """
    Scale a strategy-specific ATR stop mult by the coin override vs global default.

    Trend pullback/breakout use their own base mults; FET ``atr_multiplier=0.5`` halves them.
  """
    from strategy.liquidity_sweep_reversal.sweep_revesal_config import ATR_MULTIPLIER

    ref = max(float(ATR_MULTIPLIER), 1e-12)
    return float(base_mult) * (resolve_atr_multiplier(cfg) / ref)


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


def price_decimals_from_binance_tick(tick_size: str | float) -> int:
    """Derive display decimals from Binance ``PRICE_FILTER.tickSize`` (e.g. ``0.10`` -> 2)."""
    raw = str(tick_size).strip()
    if not raw:
        return 2
    if "." in raw:
        frac = raw.split(".", 1)[1]
        return max(0, min(16, len(frac)))
    try:
        tick = float(raw)
    except (TypeError, ValueError):
        return 2
    if tick <= 0.0:
        return 2
    if tick >= 1.0:
        return 0
    import math

    return max(0, min(16, int(round(-math.log10(tick)))))


def fetch_exchange_price_rounding_decimal(symbol: str, *, fallback: int = 2) -> int:
    """Resolve ``pricePrecision`` / ``PRICE_FILTER.tickSize`` from Binance USD-M ``exchangeInfo``."""
    sym = normalize_coin_symbol(str(symbol))
    cached = _exchange_price_decimal_cache.get(sym)
    if cached is not None:
        return cached

    out = max(0, min(16, int(fallback)))
    try:
        from config import settings

        base = str(getattr(settings, "BINANCE_FAPI_LIVE_HOST", "https://fapi.binance.com")).rstrip("/")
        url = f"{base}/fapi/v1/exchangeInfo?symbol={sym}"
        with urlopen(Request(url=url, method="GET"), timeout=15) as response:
            parsed = json.loads(response.read().decode("utf-8"))
        if isinstance(parsed, dict):
            for sym_row in parsed.get("symbols", []):
                if not isinstance(sym_row, dict):
                    continue
                if str(sym_row.get("symbol", "")).upper() != sym:
                    continue
                pp = sym_row.get("pricePrecision")
                if pp is not None:
                    out = max(0, min(16, int(pp)))
                    break
                for filt in sym_row.get("filters", []):
                    if not isinstance(filt, dict):
                        continue
                    if str(filt.get("filterType", "")).upper() != "PRICE_FILTER":
                        continue
                    out = price_decimals_from_binance_tick(str(filt.get("tickSize", "0.01")))
                    break
                break
    except Exception:
        pass

    _exchange_price_decimal_cache[sym] = out
    return out


def get_coin_config(symbol: str | None) -> dict[str, Any]:
    """Return the registered per-coin config dict (no shared base merge)."""
    if not symbol or not str(symbol).strip():
        raise ValueError("get_coin_config requires a symbol")
    sym = normalize_coin_symbol(str(symbol))
    mod = _COIN_MODULES.get(sym)
    if mod is None:
        raise ValueError(f"No coin config registered for {sym}")
    return _config_dict_for_module(mod, sym)


def price_rounding_decimal(symbol: str | None) -> int:
    """Decimals for price display in logs and Telegram (coin config or Binance ``exchangeInfo``)."""
    cfg = get_coin_config(symbol)
    raw = cfg.get("price_rounding_decimal")
    if raw is not None:
        try:
            return max(0, min(16, int(raw)))
        except (TypeError, ValueError):
            pass
    if bool(cfg.get("price_rounding_decimal_from_exchange")):
        sym = normalize_coin_symbol(str(symbol))
        return fetch_exchange_price_rounding_decimal(sym)
    return 2


def price_tick_size(symbol: str | None) -> float:
    """Binance-style price tick from coin ``price_rounding_decimal`` (e.g. 4 -> 0.0001)."""
    d = price_rounding_decimal(symbol)
    return 10 ** (-d) if d > 0 else 1.0


def resolve_bars_since_last_close_min(symbol: str | None) -> int:
    """Minimum closed 5m bars after a close before new liquidity entries (0 = disabled)."""
    if not symbol or not str(symbol).strip():
        return 0
    try:
        cfg = get_coin_config(symbol)
    except ValueError:
        return 0
    raw = cfg.get("bars_since_last_close")
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except (TypeError, ValueError):
        return 0


def max_opened_positions_for(symbol: str | None) -> int:
    """Per-symbol concurrent position cap from coin config (default 1)."""
    if not symbol or not str(symbol).strip():
        return 1
    sym = normalize_coin_symbol(symbol)
    cfg = get_coin_config(sym)
    try:
        return max(1, int(cfg.get("max_opened_positions", 1)))
    except (TypeError, ValueError):
        return 1


def max_breakout_retest_positions_for(symbol: str | None) -> int:
    """Max concurrent breakout + retest legs per symbol (default 1 = no second leg)."""
    if not symbol or not str(symbol).strip():
        return 1
    sym = normalize_coin_symbol(symbol)
    cfg = get_coin_config(sym)
    try:
        return max(1, int(cfg.get("max_breakout_retest_position", 1)))
    except (TypeError, ValueError):
        return 1


def symbol_at_per_symbol_cap(symbol: str, positions_per_symbol: dict[str, int]) -> bool:
    """True when this symbol already has ``max_opened_positions`` open books."""
    sym = normalize_coin_symbol(symbol)
    return int(positions_per_symbol.get(sym, 0)) >= max_opened_positions_for(sym)


TREND_BREAKOUT_SLOTS = frozenset({BREAKOUT.lower(), BREAKOUT_RETEST.lower()})
TREND_PULLBACK_SETUP = PULLBACK.lower()
TREND_INDEPENDENT_SETUPS = frozenset({BREAKOUT.lower(), PULLBACK.lower(), BREAKOUT_RETEST.lower()})


def is_trend_independent_setup(setup_type: str, strategy_family: str = "") -> bool:
    setup = str(setup_type or "").strip().lower()
    family = str(strategy_family or "").strip().lower()
    if family and family not in ("trend_following", "trend"):
        return False
    return setup in TREND_INDEPENDENT_SETUPS


def _open_live_positions_for_symbol(positions: list[Any], symbol: str) -> list[Any]:
    sym_u = normalize_coin_symbol(symbol)
    out: list[Any] = []
    for p in positions or []:
        psym = normalize_coin_symbol(str(getattr(p, "symbol", "")))
        if psym != sym_u:
            continue
        if bool(getattr(p, "closed", False)):
            continue
        if float(getattr(p, "qty_open", 0.0)) <= 1e-12:
            continue
        out.append(p)
    return out


def _trend_open_rows(open_rows: list[Any]) -> list[Any]:
    out: list[Any] = []
    for p in open_rows:
        p_family = str(getattr(p, "strategy_family", "")).strip().lower()
        if p_family in ("trend_following", "trend"):
            out.append(p)
    return out


def trend_setup_slot_block_reason(
    positions: list[Any],
    *,
    symbol: str,
    setup_type: str,
    direction: str,
    strategy_family: str = "",
) -> str | None:
    """
    Per symbol: max 1 breakout and 1 retest; pullback excludes breakout/retest.
    """
    if not is_trend_independent_setup(setup_type, strategy_family):
        return None
    setup = str(setup_type).strip().lower()
    direction_u = str(direction).strip().upper()
    trend_rows = _trend_open_rows(_open_live_positions_for_symbol(positions, symbol))
    open_setups = {
        str(getattr(p, "setup_type", "")).strip().lower()
        for p in trend_rows
    }
    for p in trend_rows:
        p_dir = str(getattr(p, "direction", "")).strip().upper()
        if p_dir and direction_u and p_dir != direction_u:
            return f"trend slot blocked: existing {p_dir} leg, signal {direction_u}"

    if setup == TREND_PULLBACK_SETUP:
        if open_setups & TREND_BREAKOUT_SLOTS:
            return "trend slot blocked: pullback vs breakout/retest"
        if TREND_PULLBACK_SETUP in open_setups:
            return "trend slot blocked: pullback leg already open"
        return None

    if setup == BREAKOUT.lower():
        if TREND_PULLBACK_SETUP in open_setups:
            return "trend slot blocked: breakout/retest vs pullback"
        if BREAKOUT.lower() in open_setups:
            return "trend slot blocked: breakout leg already open"
        return None

    if setup == BREAKOUT_RETEST.lower():
        if TREND_PULLBACK_SETUP in open_setups:
            return "trend slot blocked: breakout/retest vs pullback"
        if BREAKOUT_RETEST.lower() in open_setups:
            return "trend slot blocked: breakout_retest leg already open"
        return None

    return None


def _normalize_strategy_family(strategy_family: str) -> str:
    fam = str(strategy_family or "").strip().lower()
    if fam in ("trend_following", "trend"):
        return "trend"
    if fam in ("liquidity", "liquidity_sweep_reversal"):
        return "liquidity"
    return fam


def _liquidity_open_rows(open_rows: list[Any]) -> list[Any]:
    out: list[Any] = []
    for p in open_rows:
        if _normalize_strategy_family(str(getattr(p, "strategy_family", ""))) == "liquidity":
            out.append(p)
    return out


def _breakout_retest_open_count(trend_rows: list[Any]) -> int:
    return sum(
        1
        for p in trend_rows
        if str(getattr(p, "setup_type", "")).strip().lower() in TREND_BREAKOUT_SLOTS
    )


def symbol_entry_block_reason(
    symbol: str,
    positions_per_symbol: dict[str, int],
    *,
    setup_type: str = "",
    direction: str = "",
    strategy_family: str = "",
    open_positions: list[Any] | None = None,
) -> str | None:
    if open_positions is None:
        if symbol_at_per_symbol_cap(symbol, positions_per_symbol):
            sym = normalize_coin_symbol(symbol)
            cap = max_opened_positions_for(sym)
            cur = int(positions_per_symbol.get(sym, 0))
            return f"per-symbol cap ({sym} already {cur}, max {cap})"
        return None

    live = _open_live_positions_for_symbol(open_positions, symbol)
    liquidity_rows = _liquidity_open_rows(live)
    trend_rows = _trend_open_rows(live)
    fam = _normalize_strategy_family(strategy_family)
    setup = str(setup_type or "").strip().lower()
    sym = normalize_coin_symbol(symbol)

    if fam == "trend" and liquidity_rows:
        return "trend blocked: liquidity_sweep_reversal open"
    if fam == "liquidity" and trend_rows:
        return "liquidity blocked: trend following open"

    if fam == "trend" and is_trend_independent_setup(setup_type, strategy_family):
        trend_block = trend_setup_slot_block_reason(
            open_positions,
            symbol=sym,
            setup_type=setup,
            direction=direction,
            strategy_family=strategy_family,
        )
        if trend_block is not None:
            return trend_block
        if setup in TREND_BREAKOUT_SLOTS:
            br_open = _breakout_retest_open_count(trend_rows)
            max_br = max_breakout_retest_positions_for(sym)
            if br_open >= max_br:
                return f"trend slot blocked: breakout/retest cap ({br_open}/{max_br})"
            return None
        per_sym_cap = max_opened_positions_for(sym)
        if len(trend_rows) >= per_sym_cap:
            return f"trend slot blocked: per-symbol cap ({len(trend_rows)}/{per_sym_cap})"
        return None

    if fam == "liquidity":
        per_sym_cap = max_opened_positions_for(sym)
        if len(live) >= per_sym_cap:
            return f"per-symbol cap ({sym} already {len(live)}, max {per_sym_cap})"
        return None

    if symbol_at_per_symbol_cap(symbol, positions_per_symbol):
        cap = max_opened_positions_for(sym)
        cur = int(positions_per_symbol.get(sym, 0))
        return f"per-symbol cap ({sym} already {cur}, max {cap})"
    return None


def symbol_entry_blocked(
    symbol: str,
    positions_per_symbol: dict[str, int],
    *,
    setup_type: str = "",
    direction: str = "",
    strategy_family: str = "",
    open_positions: list[Any] | None = None,
) -> bool:
    return (
        symbol_entry_block_reason(
            symbol,
            positions_per_symbol,
            setup_type=setup_type,
            direction=direction,
            strategy_family=strategy_family,
            open_positions=open_positions,
        )
        is not None
    )


def register_coin_module(symbol_usdt: str, module: Any) -> None:
    """Register extra coin overrides at runtime (e.g. for scaling past static files)."""
    _COIN_MODULES[normalize_coin_symbol(symbol_usdt)] = module


def passes_coin_execution_gates(trade_data: dict[str, Any]) -> bool:
    """Reject if TP1 R-multiple, score, grade, or confirmation_mode violate coin config."""
    sym = trade_data.get("symbol")
    if not sym:
        return False
    cfg = get_coin_config(str(sym))

    score = float(trade_data.get("setup_score") or 0)
    if score < float(cfg["min_setup_score"]):
        return False

    grade = str(trade_data.get("setup_grade", "") or "").strip().upper()
    allowed = [str(x).strip().upper() for x in cfg["allowed_grades"]]
    if grade not in allowed:
        return False

    cm = str(trade_data.get("confirmation_mode", "") or "").strip().lower()
    modes = [str(m).strip().lower() for m in cfg["confirmation_modes"]]
    if cm not in modes:
        return False

    entry = float(trade_data.get("entry") or 0)
    sl = float(trade_data.get("stop_loss") or 0)
    tp1 = float(trade_data.get("tp1") or 0)
    if entry <= 0:
        return False
    risk = abs(entry - sl)
    reward = abs(tp1 - entry)
    if risk <= 0:
        return False
    rr = reward / risk
    if coin_enforces_min_risk_reward(cfg) and rr < float(cfg["min_risk_reward_multiple"]):
        return False
    return True
