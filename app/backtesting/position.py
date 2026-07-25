from __future__ import annotations

from datetime import datetime
from typing import Any

from dataclasses import asdict

from backtesting.account import BacktestAccountService, BacktestAccountState
from backtesting.config import FEES, SLIPPAGE_BPS
from backtesting.models import BacktestPosition, BacktestTrade, EquityPoint
from order_planner.models import OrderPlan
from position.archive import archive_position, save_runtime_position
from analysis.collect_position_metrics import update_entry_result


class BacktestPositionManager:
    def __init__(self, initial_balance: float = 100) -> None:
        self.account = BacktestAccountService(initial_balance)
        self.positions: dict[str, BacktestPosition] = {}
        self.closed_positions: list[BacktestPosition] = []
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = []

    def can_open_position(self, symbol: str) -> bool:
        return symbol not in self.positions

    def open_position(
        self,
        order_plan: OrderPlan,
        timestamp: datetime,
        position_id: str = "",
    ) -> BacktestPosition:
        position = self._build_position(
            order_plan=order_plan,
            timestamp=timestamp,
            position_id=position_id,
            wallet_balance=self.account.wallet_balance,
        )
        self.positions[order_plan.symbol] = position
        self.account.available_balance -= order_plan.margin_usdt
        save_runtime_position(asdict(position))
        return position

    @staticmethod
    def _build_position(
        order_plan: OrderPlan,
        timestamp: datetime,
        position_id: str = "",
        wallet_balance: float = 0.0,
    ) -> BacktestPosition:
        return BacktestPosition(
            position_id=position_id,
            symbol=order_plan.symbol,
            direction=order_plan.direction,
            strategy_family=order_plan.strategy_family,
            setup_type=order_plan.setup_type,
            setup_score=order_plan.setup_score,
            entry_time=timestamp,
            entry=order_plan.entry,
            initial_qty=order_plan.qty,
            remaining_qty=order_plan.qty,
            stop_loss=order_plan.stop_loss,
            risk_amount=order_plan.risk_amount,
            margin_usdt=order_plan.margin_usdt,
            tp1=order_plan.tp1,
            tp2=order_plan.tp2,
            tp3=order_plan.tp3,
            tp1_pct=order_plan.tp1_pct,
            tp2_pct=order_plan.tp2_pct,
            tp3_pct=order_plan.tp3_pct,
            tp1_qty=order_plan.tp1_qty,
            tp2_qty=order_plan.tp2_qty,
            tp3_qty=order_plan.tp3_qty,
            balance_usdt=wallet_balance,
            opened=timestamp,
            status="Open",
        )

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

    def _process_take_profits(
        self,
        pos: BacktestPosition,
        symbol: str,
        high: float,
        low: float,
        is_long: bool,
        timestamp: datetime,
    ) -> None:
        for tp in pos.take_profits:
            if tp.hit:
                continue

            touched = high >= tp.price if is_long else low <= tp.price
            if not touched:
                continue

            exit_price = self._apply_slippage(tp.price, is_long)

            self.close_position(
                symbol=symbol,
                exit_price=exit_price,
                reason=f"TP{tp.level}",
                timestamp=timestamp,
                qty=tp.qty,
            )

            tp.hit = True

            if tp.trail_to is not None:
                if is_long:
                    pos.stop_loss = max(pos.stop_loss, tp.trail_to)
                else:
                    pos.stop_loss = min(pos.stop_loss, tp.trail_to)

    def _process_stop_loss(
        self,
        pos: BacktestPosition,
        symbol: str,
        high: float,
        low: float,
        is_long: bool,
        timestamp: datetime,
    ) -> None:
        hit = low <= pos.stop_loss if is_long else high >= pos.stop_loss

        if not hit:
            return

        exit_price = self._apply_slippage(pos.stop_loss, is_long)

        self.close_position(
            symbol=symbol,
            exit_price=exit_price,
            reason="STOP_LOSS",
            timestamp=timestamp,
        )

    def _apply_slippage(self, price: float, is_long: bool) -> float:
        multiplier = (
            1 - SLIPPAGE_BPS / 10000
            if is_long
            else 1 + SLIPPAGE_BPS / 10000
        )
        return price * multiplier

    def close_position(
        self,
        symbol: str,
        exit_price: float,
        exit_reason: str,
        timestamp: datetime,
        qty: float | None = None,
    ) -> BacktestTrade | None:

        pos = self.positions.get(symbol)
        if pos is None:
            return None

        close_qty = qty or pos.remaining_qty
        if close_qty <= 0:
            return None

        trade = self._build_trade(
            pos,
            close_qty,
            exit_price,
            exit_reason,
            timestamp,
        )

        self.trades.append(trade)

        self._update_position(pos, trade)

        self._update_account(trade)

        if pos.remaining_qty <= 0:
            self._finalize_position(symbol, pos, timestamp, exit_reason)

        return trade

    def _build_trade(
        self,
        pos: BacktestPosition,
        qty: float,
        exit_price: float,
        reason: str,
        timestamp: datetime,
    ) -> BacktestTrade:

        pnl = self._calculate_pnl(pos, qty, exit_price)
        fee = qty * exit_price * FEES
        net_pnl = pnl - fee

        return BacktestTrade(
            symbol=pos.symbol,
            direction=pos.direction,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            entry_price=pos.entry,
            exit_price=exit_price,
            qty=qty,
            pnl=pnl,
            fee=fee,
            net_pnl=net_pnl,
            exit_reason=reason,
            setup_type=pos.setup_type,
            setup_score=pos.setup_score,
            setup_grade=pos.setup_grade,
            risk_amount=pos.risk_amount,
        )

    def _update_position(
        self,
        pos: BacktestPosition,
        trade: BacktestTrade,
    ) -> None:

        pos.remaining_qty -= trade.qty
        pos.realized_pnl += trade.net_pnl

    def _update_account(
        self,
        trade: BacktestTrade,
    ) -> None:
        self.account.apply_realized_pnl(trade.net_pnl)

    def _finalize_position(
        self,
        symbol: str,
        pos: BacktestPosition,
        timestamp: datetime,
        reason: str,
    ) -> None:

        self._release_margin(pos)

        archive_position(
            asdict(pos) | {
                "closed": timestamp.isoformat(),
                "exit_reason": reason,
            }
        )

        self._update_runtime_result(pos, reason)

        self.closed_positions.append(pos)
        del self.positions[symbol]

    def _release_margin(self, pos: BacktestPosition) -> None:
        self.account.wallet_balance += pos.margin_usdt
        self.account.available_balance += pos.margin_usdt

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

    def _calculate_pnl(
        self,
        pos: BacktestPosition,
        qty: float,
        exit_price: float,
    ) -> float:

        if pos.direction == "LONG":
            return qty * (exit_price - pos.entry)

        return qty * (pos.entry - exit_price)

    def get_backtest_result(self) -> dict[str, Any]:
        return {
            "trades": self.trades,
            "positions": self.closed_positions,
            "equity_curve": self.equity_curve,
            "final_balance": self.account.wallet_balance,
        }
