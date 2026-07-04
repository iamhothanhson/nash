from __future__ import annotations

from typing import Any, Mapping

from coins.loader import get_coin_config, passes_coin_execution_gates


def ai_gate_score_tier(signal: Any, plan: Mapping[str, Any] | None = None) -> bool:
    """Use AI only for A-grade setups with setup_score in [min_setup_score, 10]."""

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

    grade = ""
    score = 0.0

    if plan is not None:
        grade = str(plan.get("setup_grade") or "").strip().upper()
        score = float(plan.get("setup_score") or 0)

    if not grade:
        grade = str(get_field(signal, "setup_grade", "") or "").strip().upper()

    if score == 0:
        score = float(get_field(signal, "setup_score", 0) or 0)

    lo = float(cfg["min_setup_score"])
    return grade == "A" and lo <= score <= 10.0


def ai_gate_trade_metrics(trade_data: dict) -> bool:
    entry = trade_data.get("entry")
    stop_loss = trade_data.get("stop_loss")
    tp1 = trade_data.get("tp1")
    if entry is None or stop_loss is None or tp1 is None:
        return False
    return passes_coin_execution_gates(trade_data)
