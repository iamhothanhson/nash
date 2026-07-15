from __future__ import annotations

from datetime import datetime
from typing import Any

from backtesting.config import SLIPPAGE_BPS
from backtesting.position import BacktestPositionManager


class BacktestExecutor:
    def execute(
        self,
        order_plan: dict[str, Any],
        candle: Any,
        timestamp: datetime,
        portfolio: BacktestPositionManager,
    ) -> dict[str, Any]:
        symbol = order_plan["symbol"]
        direction = order_plan["direction"]
        entry = float(candle["close"])

        slippage = entry * SLIPPAGE_BPS / 10000
        entry = entry + slippage if direction == "LONG" else entry - slippage

        sl = order_plan["stop_loss"]
        tp1 = order_plan["tp1"]
        tp2 = order_plan["tp2"]
        tp3 = order_plan.get("tp3", 0.0)
        qty = order_plan["qty"]
        risk_amount = order_plan["risk_amount"]

        tp1_qty = qty * 0.5
        tp2_qty = qty * 0.3
        tp3_qty = qty * 0.2

        portfolio.open_position(
            symbol=symbol,
            direction=direction,
            entry=entry,
            stop_loss=sl,
            tp1=tp1, tp2=tp2, tp3=tp3,
            qty=qty,
            tp1_qty=tp1_qty, tp2_qty=tp2_qty, tp3_qty=tp3_qty,
            risk_amount=risk_amount,
            timestamp=timestamp,
            setup_type=order_plan.get("setup_type"),
            setup_score=order_plan.get("setup_score", 0.0),
        )

        return {"status": "opened", "symbol": symbol, "direction": direction, "entry": entry, "qty": qty}
