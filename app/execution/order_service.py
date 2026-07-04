from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from execution.exchange_order_gateway import ExchangeOrderGateway
from execution.position_mode import position_side_for_entry
from execution.risk_manager import RiskConfig, calculate_position_size, validate_trade

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderDecision:
    symbol: str
    action: str  # BUY | SELL | HOLD
    confidence: float


class OrderService:
    """Execution orchestrator: validate -> size -> send order."""

    def __init__(self, order_executor: ExchangeOrderGateway, risk_config: RiskConfig | None = None) -> None:
        self.order_executor = order_executor
        self.risk_config = risk_config or RiskConfig()

    def execute(self, decision: dict[str, Any]) -> dict[str, Any]:
        ok, reason = validate_trade(decision, self.risk_config)
        if not ok:
            log.info("Trade rejected: %s", reason)
            return {"executed": False, "reason": reason}

        balance = float(decision.get("balance", 0.0))
        if balance <= 0:
            try:
                balance = float(self.order_executor.exchange_client.get_balance())
            except Exception as exc:
                return {"executed": False, "reason": f"failed to fetch balance: {exc}"}

        risk_percent = float(decision.get("risk_percent", self.risk_config.max_risk_per_trade))
        notional = calculate_position_size(balance, risk_percent)

        amount = decision.get("amount")
        if amount is None:
            price = float(decision.get("price", 0.0))
            if price <= 0:
                return {"executed": False, "reason": "missing price for amount calculation"}
            amount = notional / price
        amount = float(amount)
        if amount <= float(self.risk_config.min_entry_position_qty):
            return {"executed": False, "reason": "Amount below minimum entry position qty"}

        action = str(decision["action"]).upper()
        position_side = decision.get("position_side")
        if position_side is None and self.order_executor.exchange_client.use_hedge_position_side():
            position_side = position_side_for_entry(action)
        order = self.order_executor.create_market_order(
            symbol=str(decision["symbol"]),
            side=action,
            amount=amount,
            position_side=str(position_side) if position_side else None,
        )
        return {
            "executed": True,
            "order": order,
            "amount": amount,
            "risk_percent": risk_percent,
        }
