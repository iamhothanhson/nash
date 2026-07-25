from __future__ import annotations

from datetime import datetime
from typing import Any

from dataclasses import asdict

from backtesting.account import BacktestAccountService, BacktestAccountState
from backtesting.models import BacktestPosition, BacktestTrade, EquityPoint
from backtesting.position.builder import build_position
from backtesting.position.closing import Closing
from backtesting.position.exit import Exit
from order_planner.models import OrderPlan
from position.archive import save_runtime_position


class BacktestPositionManager(Exit, Closing):
    def __init__(self, initial_balance: float = 100) -> None:
        self.account = BacktestAccountService(initial_balance)
        self.positions: dict[str, BacktestPosition] = {}
        self.closed_positions: list[BacktestPosition] = []
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = []

    def can_open_position(self, symbol: str) -> bool:
        return symbol not in self.positions

    def get_account_state(self) -> BacktestAccountState:
        return self.account.get_account_state()

    def open_position(
        self,
        order_plan: OrderPlan,
        timestamp: datetime,
        position_id: str = "",
    ) -> BacktestPosition:
        position = build_position(
            order_plan=order_plan,
            timestamp=timestamp,
            position_id=position_id,
            wallet_balance=self.account.wallet_balance,
        )
        self.positions[order_plan.symbol] = position
        self.account.available_balance -= order_plan.margin_usdt
        save_runtime_position(asdict(position))
        return position

    def update_positions(self, symbol: str, candle: Any, timestamp: datetime) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            return

        high = float(candle["high"])
        low = float(candle["low"])
        is_long = pos.direction == "LONG"

        self._process_take_profits(pos, symbol, high, low, is_long, timestamp)

        if symbol in self.positions:
            self._process_stop_loss(pos, symbol, high, low, is_long, timestamp)

    def record_equity(self, timestamp: datetime) -> None:
        upnl = 0.0
        for pos in self.positions.values():
            upnl += pos.realized_pnl
        balance = self.account.wallet_balance
        self.equity_curve.append(EquityPoint(
            timestamp=timestamp,
            balance=balance,
            unrealized_pnl=upnl,
            equity=balance + upnl,
        ))

    def get_backtest_result(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "positions": self.closed_positions,
            "equity_curve": self.equity_curve,
            "final_balance": self.account.wallet_balance,
        }
