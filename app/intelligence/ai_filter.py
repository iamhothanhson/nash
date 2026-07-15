from __future__ import annotations

from typing import Any, Mapping

from coins.loader import get_coin_config


def ai_gate_score_tier(signal: Any, plan: Mapping[str, Any] | None = None) -> bool:
    """Use AI only for signals with setup_score in [min_setup_score, 10]."""

    def get_field(obj: Any, key: str, default=None):
        if isinstance(obj, Mapping):
            return obj.get(key, default)
        return getattr(obj, key, default)

    sym: str | None = None
    if plan is not None:
        raw_sym = plan.get("symbol")
        if raw_sym is not None:
            sym = str(raw_sym)
    if not sym:
        sym = get_field(signal, "symbol", None)
    if not sym:
        return False
    cfg = get_coin_config(str(sym))

    score = 0.0

    if plan is not None:
        score = float(plan.get("setup_score") or 0)

    if score == 0:
        score = float(get_field(signal, "setup_score", 0) or 0)

    lo = float(cfg["min_setup_score"])
    return lo <= score <= 10.0


def _coin_enforces_min_risk_reward(cfg: dict[str, Any]) -> bool:
    raw = cfg.get("enforce_min_risk_reward_multiple")
    if raw is None:
        return True
    return bool(raw)


def _passes_coin_execution_gates(trade_data: dict[str, Any]) -> bool:
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
    if _coin_enforces_min_risk_reward(cfg) and rr < float(cfg["min_risk_reward_multiple"]):
        return False
    return True


def ai_gate_trade_metrics(trade_data: dict) -> bool:
    entry = trade_data.get("entry")
    stop_loss = trade_data.get("stop_loss")
    tp1 = trade_data.get("tp1")
    if entry is None or stop_loss is None or tp1 is None:
        return False
    return _passes_coin_execution_gates(trade_data)
