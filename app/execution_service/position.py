# position/service.py

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.logger import log
from config import settings
from execution_service.models import ExecutionResult
from order_planner.models import OrderPlan
from position.archive import save_runtime_position


class PositionService:
    """Creates and persists runtime position tracking data."""

    def record_position(
        self,
        *,
        plan: OrderPlan,
        execution: ExecutionResult,
    ) -> dict[str, Any]:
        position = self._build_position_data(
            plan=plan,
            execution=execution,
        )

        save_runtime_position(position)

        log(
            f"[POSITION] {execution.symbol} | "
            "Runtime position recorded"
        )

        return position

    def _build_position_data(
        self,
        *,
        plan: OrderPlan,
        execution: ExecutionResult,
    ) -> dict[str, Any]:
        leverage = self._get_leverage()

        size_usdt = (
            float(plan.notional)
            if plan.notional
            else execution.filled_qty * execution.entry_price
        )

        margin_usdt = size_usdt / leverage

        sl_percent = self._calculate_price_percent(
            entry_price=execution.entry_price,
            target_price=plan.stop_loss,
            direction=execution.direction,
            target_type="stop_loss",
        )

        tp1_percent = self._calculate_price_percent(
            entry_price=execution.entry_price,
            target_price=plan.tp1,
            direction=execution.direction,
            target_type="take_profit",
        )

        tp2_percent = self._calculate_price_percent(
            entry_price=execution.entry_price,
            target_price=plan.tp2,
            direction=execution.direction,
            target_type="take_profit",
        )

        tp3_percent = self._calculate_price_percent(
            entry_price=execution.entry_price,
            target_price=plan.tp3,
            direction=execution.direction,
            target_type="take_profit",
        )

        return {
            "status": "Open",
            "symbol": execution.symbol,
            "side": execution.direction,
            "position_side": execution.position_side,
            "strategy": plan.strategy_family,
            "setup": plan.setup_type,
            "size_usdt": round(size_usdt, 2),
            "margin_usdt": round(margin_usdt, 2),
            "entry": {
                "price": execution.entry_price,
                "quantity": execution.filled_qty,
                "order_id": execution.entry_order_id,
            },
            "stop_loss": {
                "price": plan.stop_loss,
                "percent": round(sl_percent, 2),
                "risk_usdt": plan.risk_amount,
                "order_id": execution.stop_loss_order_id,
                "hit": False,
            },
            "take_profit": [
                {
                    "name": "tp1",
                    "execution_mode": "exchange_order",
                    "price": plan.tp1,
                    "percent": round(tp1_percent, 2),
                    "quantity": plan.tp1_qty,
                    "partial_close_percent": 50.0,
                    "order_id": execution.tp1_order_id,
                    "hit": False,
                },
                {
                    "name": "tp2",
                    "execution_mode": "managed",
                    "price": plan.tp2,
                    "percent": round(tp2_percent, 2),
                    "quantity": plan.tp2_qty,
                    "partial_close_percent": 30.0,
                    "order_id": None,
                    "hit": False,
                },
                {
                    "name": "tp3",
                    "execution_mode": "managed",
                    "price": plan.tp3,
                    "percent": round(tp3_percent, 2),
                    "quantity": plan.tp3_qty,
                    "partial_close_percent": 20.0,
                    "order_id": None,
                    "hit": False,
                },
            ],
            "pnl_usdt": 0.0,
            "exchange_pnl_usdt": None,
            "balance_usdt": 0.0,
            "closed_reason": None,
            "opened_at": datetime.now(timezone.utc).isoformat(),
            "closed_at": None,
        }

    @staticmethod
    def _calculate_price_percent(
        *,
        entry_price: float,
        target_price: float,
        direction: str,
        target_type: str,
    ) -> float:
        if entry_price <= 0:
            return 0.0

        normalized_direction = direction.upper()

        if target_type == "take_profit":
            difference = (
                target_price - entry_price
                if normalized_direction == "LONG"
                else entry_price - target_price
            )
        elif target_type == "stop_loss":
            difference = (
                entry_price - target_price
                if normalized_direction == "LONG"
                else target_price - entry_price
            )
        else:
            raise ValueError(
                f"Unsupported target type: {target_type}"
            )

        return difference / entry_price * 100

    @staticmethod
    def _get_leverage() -> float:
        leverage = float(settings.LEVERAGE or 1)

        if leverage <= 0:
            raise ValueError(
                f"LEVERAGE must be greater than zero, got {leverage}"
            )

        return leverage