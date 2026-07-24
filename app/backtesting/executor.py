from __future__ import annotations

from datetime import datetime
from typing import Any

from backtesting.config import SLIPPAGE_BPS
from backtesting.position import BacktestPositionManager
from analysis.collect_position_metrics import build_entry_snapshot, save_entry_snapshot


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

        ts_id = int(timestamp.timestamp() * 1_000_000) if hasattr(timestamp, "timestamp") else int(timestamp)
        position_id = f"{ts_id}_{symbol}_{direction}"

        entry_snapshot = build_entry_snapshot(
            order_plan.get("market_state"), order_plan.get("features"),
            symbol=symbol, side=direction,
            strategy_setup=order_plan.get("setup_type", ""),
            position_id=position_id,
            setup_score=float(order_plan.get("setup_score", 0.0)),
            captured_at=timestamp,
        )
        save_entry_snapshot(entry_snapshot)

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
            position_id=position_id,
        )

        return {"status": "opened", "symbol": symbol, "direction": direction, "entry": entry, "qty": qty}
