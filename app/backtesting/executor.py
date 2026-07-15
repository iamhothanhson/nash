from __future__ import annotations

from datetime import datetime
from typing import Any

from backtesting.portfolio import BacktestPortfolio


SLIPPAGE_BPS = 5

class BacktestExecutor:
    def update_positions(
        self,
        symbol: str,
        candle: Any,
        timestamp: datetime,
        portfolio: BacktestPortfolio,
    ) -> None:
        pos = portfolio.positions.get(symbol)
        if pos is None:
            return

        high = float(candle["high"])
        low = float(candle["low"])

        if pos.direction == "LONG":
            if not pos.tp1_hit and high >= pos.tp1:
                exit_price = pos.tp1 * (1 - SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "TP1", timestamp, qty=pos.tp1_qty)
                pos.tp1_hit = True
                pos.stop_loss = max(pos.stop_loss, pos.entry)

            if pos.tp1_hit and not pos.tp2_hit and high >= pos.tp2:
                exit_price = pos.tp2 * (1 - SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "TP2", timestamp, qty=pos.tp2_qty)
                pos.tp2_hit = True
                pos.stop_loss = max(pos.stop_loss, pos.tp1)

            if pos.tp2_hit and not pos.tp3_hit and high >= pos.tp3:
                exit_price = pos.tp3 * (1 - SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "TP3", timestamp, qty=pos.tp3_qty)
                pos.tp3_hit = True

            if low <= pos.stop_loss and portfolio.positions.get(symbol) is not None:
                exit_price = pos.stop_loss * (1 - SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "STOP_LOSS", timestamp)

        else:
            if not pos.tp1_hit and low <= pos.tp1:
                exit_price = pos.tp1 * (1 + SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "TP1", timestamp, qty=pos.tp1_qty)
                pos.tp1_hit = True
                pos.stop_loss = min(pos.stop_loss, pos.entry)

            if pos.tp1_hit and not pos.tp2_hit and low <= pos.tp2:
                exit_price = pos.tp2 * (1 + SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "TP2", timestamp, qty=pos.tp2_qty)
                pos.tp2_hit = True
                pos.stop_loss = min(pos.stop_loss, pos.tp1)

            if pos.tp2_hit and not pos.tp3_hit and low <= pos.tp3:
                exit_price = pos.tp3 * (1 + SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "TP3", timestamp, qty=pos.tp3_qty)
                pos.tp3_hit = True

            if high >= pos.stop_loss and portfolio.positions.get(symbol) is not None:
                exit_price = pos.stop_loss * (1 + SLIPPAGE_BPS / 10000)
                portfolio.close_position(symbol, exit_price, "STOP_LOSS", timestamp)

    def execute(
        self,
        order_plan: dict[str, Any],
        candle: Any,
        timestamp: datetime,
        portfolio: BacktestPortfolio,
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
