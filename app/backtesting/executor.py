from __future__ import annotations

from datetime import datetime

from backtesting.config import SLIPPAGE_BPS
from backtesting.marketplace import HistoricalMarketplace
from backtesting.position import BacktestPositionManager
from order_planner.models import OrderPlan
from setup_builder.grader import Grader
from analysis.collect_position_metrics import build_entry_snapshot, save_entry_snapshot


class BacktestExecutor:
    def __init__(
        self,
        marketplace: HistoricalMarketplace,
        position_manager: BacktestPositionManager,
    ):
        self.marketplace = marketplace
        self.position_manager = position_manager

    def execute(
        self,
        order_plan: OrderPlan,
        timestamp: datetime,
    ) -> dict | None:
        candle = self.marketplace.get_candle(
            symbol=order_plan.symbol, timestamp=timestamp,
        )
        if candle is None:
            return None

        entry = float(candle["close"])
        slippage = entry * SLIPPAGE_BPS / 10000
        entry = entry + slippage if order_plan.direction == "LONG" else entry - slippage

        ts_id = int(timestamp.timestamp() * 1_000_000) if hasattr(timestamp, "timestamp") else int(timestamp)
        position_id = f"{ts_id}_{order_plan.symbol}_{order_plan.direction}"

        entry_snapshot = build_entry_snapshot(
            order_plan.market_state, order_plan.features,
            symbol=order_plan.symbol, side=order_plan.direction,
            strategy_setup=order_plan.setup_type,
            position_id=position_id,
            setup_score=order_plan.setup_score,
            captured_at=timestamp,
        )
        save_entry_snapshot(entry_snapshot)

        self.position_manager.open_position(
            order_plan=order_plan,
            timestamp=timestamp,
            position_id=position_id,
        )

        return {"status": "opened", "symbol": order_plan.symbol, "direction": order_plan.direction, "entry": entry, "qty": order_plan.qty}
