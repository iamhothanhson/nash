from __future__ import annotations

from dataclasses import dataclass

from common.rounding import round_ratio, round_usd
from config import settings
from monitoring.logger import log as daily_log


@dataclass(frozen=True)
class PositionPlan:
    notional: float
    qty: float
    # Quote-currency loss to stop (notional * sl_distance) after sizing caps.
    risk_amount: float


@dataclass(frozen=True)
class RiskConfig:
    max_risk_per_trade: float = float(settings.MAX_EXECUTION_RISK_PER_TRADE)
    min_confidence: float = 0.55
    min_entry_position_qty: float = float(getattr(settings, "MIN_QTY_PER_TRADE", 0.0))


def calculate_position_size(balance: float, risk_percent: float) -> float:
    """Simple position sizing by risk budget in quote currency."""
    safe_balance = max(0.0, float(balance))
    safe_risk = min(1.0, max(0.0, float(risk_percent)))
    return safe_balance * safe_risk


def calculate_position_plan(
    balance: float,
    risk_per_trade: float,
    sl_distance: float,
    entry_price: float,
    leverage: float,
    max_notional: float,
    max_notional_account_cap: float | None = None,
    max_execution_risk_per_trade: float | None = None,
    trade_symbol: str | None = None,
    max_order_qty: float | None = None,
) -> PositionPlan:
    sl_d = max(float(sl_distance), 1e-12)
    safe_balance = max(0.0, float(balance))
    lev_cap = safe_balance * max(1.0, float(leverage))
    max_n = max(0.0, float(max_notional))

    risk_budget = safe_balance * float(risk_per_trade)
    notional = risk_budget / sl_d
    notional = min(notional, max_n, lev_cap)
    if max_notional_account_cap is not None:
        notional = min(notional, max(0.0, float(max_notional_account_cap)))

    mexec = (
        float(max_execution_risk_per_trade)
        if max_execution_risk_per_trade is not None
        else float(settings.MAX_EXECUTION_RISK_PER_TRADE)
    )
    mexec = max(0.0, mexec)
    max_allowed_risk = safe_balance * mexec
    initial_notional = notional
    actual_risk = initial_notional * sl_d
    if actual_risk > max_allowed_risk + 1e-12:
        notional = max_allowed_risk / sl_d
        notional = min(notional, max_n, lev_cap)
        if max_notional_account_cap is not None:
            notional = min(notional, max(0.0, float(max_notional_account_cap)))
        final_notional = notional
        sym_u = str(trade_symbol).strip().upper() if trade_symbol else "—"
        mode_u = str(getattr(settings, "MODE", "unknown")).strip().upper()
        daily_log(
            f"[NOTIONAL ADJUSTED]| {sym_u} sl_distance={round_ratio(float(sl_d), 6)} "
            f"initial_notional={round_usd(float(initial_notional), 2)} "
            f"final_notional={round_usd(float(final_notional), 2)} "
            f"actual_risk={round_usd(float(actual_risk), 2)} "
            f"max_allowed_risk={round_usd(float(max_allowed_risk), 2)}"
        )

    entry_px = max(float(entry_price), 1e-12)
    if max_order_qty is not None:
        cap_q = max(0.0, float(max_order_qty))
        if cap_q > 0.0:
            notional = min(float(notional), cap_q * entry_px)
    qty = notional / entry_px
    if max_order_qty is not None:
        cap_q = max(0.0, float(max_order_qty))
        if cap_q > 0.0 and qty > cap_q:
            qty = cap_q
            notional = qty * entry_px
    effective_risk = notional * sl_d
    return PositionPlan(notional=notional, qty=qty, risk_amount=effective_risk)


def validate_trade(decision: dict, config: RiskConfig) -> tuple[bool, str | None]:
    action = str(decision.get("action", "")).upper()
    confidence = float(decision.get("confidence", 0.0))

    if action == "HOLD":
        return False, "action is HOLD"
    if action not in {"BUY", "SELL"}:
        return False, f"unsupported action: {action}"
    if confidence < config.min_confidence:
        return False, "confidence below threshold"

    risk_percent = float(decision.get("risk_percent", config.max_risk_per_trade))
    if risk_percent <= 0:
        return False, "risk_percent must be positive"
    if risk_percent > config.max_risk_per_trade:
        return False, "risk_percent exceeds max_risk_per_trade"

    return True, None
