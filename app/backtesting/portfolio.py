from __future__ import annotations

from datetime import datetime
from typing import Any

from backtesting.account import BacktestAccountService, BacktestAccountState
from backtesting.models import BacktestPosition, BacktestTrade, EquityPoint


FEES = 0.0004


class BacktestPortfolio:
    def __init__(self, initial_balance: float = 10000.0) -> None:
        self.account = BacktestAccountService(initial_balance)
        self.positions: dict[str, BacktestPosition] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = []

    def can_open_position(self, symbol: str) -> bool:
        return symbol not in self.positions

    def get_account_state(self) -> BacktestAccountState:
        return self.account.get_account_state()

    def open_position(self, symbol: str, direction: str, entry: float,
                      stop_loss: float, tp1: float, tp2: float, tp3: float,
                      qty: float, tp1_qty: float, tp2_qty: float, tp3_qty: float,
                      risk_amount: float, timestamp: datetime,
                      setup_type: str | None = None,
                      setup_score: float = 0.0) -> BacktestPosition:
        pos = BacktestPosition(
            symbol=symbol,
            direction=direction,
            entry_time=timestamp,
            entry=entry,
            stop_loss=stop_loss,
            tp1=tp1, tp2=tp2, tp3=tp3,
            initial_qty=qty,
            remaining_qty=qty,
            tp1_qty=tp1_qty, tp2_qty=tp2_qty, tp3_qty=tp3_qty,
            risk_amount=risk_amount,
            setup_type=setup_type,
            setup_score=setup_score,
        )
        self.positions[symbol] = pos
        self.account.wallet_balance -= risk_amount
        self.account.available_balance -= risk_amount
        return pos

    def close_position(self, symbol: str, exit_price: float,
                       exit_reason: str, timestamp: datetime,
                       qty: float | None = None) -> BacktestTrade | None:
        pos = self.positions.get(symbol)
        if pos is None:
            return None

        close_qty = qty if qty is not None else pos.remaining_qty
        if close_qty <= 0:
            return None

        pnl = close_qty * (exit_price - pos.entry) if pos.direction == "LONG" else close_qty * (pos.entry - exit_price)
        fee = close_qty * exit_price * FEES
        net_pnl = pnl - fee

        trade = BacktestTrade(
            symbol=symbol,
            direction=pos.direction,
            entry_time=pos.entry_time,
            exit_time=timestamp,
            entry_price=pos.entry,
            exit_price=exit_price,
            qty=close_qty,
            pnl=pnl,
            fee=fee,
            net_pnl=net_pnl,
            exit_reason=exit_reason,
            setup_type=pos.setup_type,
            setup_score=pos.setup_score,
        )
        self.trades.append(trade)

        pos.remaining_qty -= close_qty
        pos.realized_pnl += net_pnl

        self.account.apply_realized_pnl(net_pnl)
        self.account.available_balance += net_pnl

        if pos.remaining_qty <= 0:
            margin_release = pos.risk_amount
            self.account.wallet_balance += margin_release
            self.account.available_balance += margin_release
            del self.positions[symbol]

        return trade

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
            "equity_curve": self.equity_curve,
            "final_balance": self.account.wallet_balance,
        }

    @property
    def open_positions(self) -> list[BacktestPosition]:
        return list(self.positions.values())
