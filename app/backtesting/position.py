from __future__ import annotations

from datetime import datetime
from typing import Any

from backtesting.account import BacktestAccountService, BacktestAccountState
from backtesting.config import FEES, SLIPPAGE_BPS
from backtesting.models import BacktestPosition, BacktestTrade, EquityPoint


class BacktestPositionManager:
    def __init__(self, initial_balance: float = 100) -> None:
        self.account = BacktestAccountService(initial_balance)
        self.positions: dict[str, BacktestPosition] = {}
        self.trades: list[BacktestTrade] = []
        self.equity_curve: list[EquityPoint] = []

    def can_open_position(self, symbol: str) -> bool:
        return symbol not in self.positions

    def update_positions(self, symbol: str, candle: Any, timestamp: datetime) -> None:
        pos = self.positions.get(symbol)
        if pos is None:
            return

        high = float(candle["high"])
        low = float(candle["low"])

        if pos.direction == "LONG":
            if not pos.tp1_hit and high >= pos.tp1:
                exit_price = pos.tp1 * (1 - SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "TP1", timestamp, qty=pos.tp1_qty)
                pos.tp1_hit = True
                pos.stop_loss = max(pos.stop_loss, pos.entry)

            if pos.tp1_hit and not pos.tp2_hit and high >= pos.tp2:
                exit_price = pos.tp2 * (1 - SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "TP2", timestamp, qty=pos.tp2_qty)
                pos.tp2_hit = True
                pos.stop_loss = max(pos.stop_loss, pos.tp1)

            if pos.tp2_hit and not pos.tp3_hit and high >= pos.tp3:
                exit_price = pos.tp3 * (1 - SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "TP3", timestamp, qty=pos.tp3_qty)
                pos.tp3_hit = True

            if low <= pos.stop_loss and symbol in self.positions:
                exit_price = pos.stop_loss * (1 - SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "STOP_LOSS", timestamp)

        else:
            if not pos.tp1_hit and low <= pos.tp1:
                exit_price = pos.tp1 * (1 + SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "TP1", timestamp, qty=pos.tp1_qty)
                pos.tp1_hit = True
                pos.stop_loss = min(pos.stop_loss, pos.entry)

            if pos.tp1_hit and not pos.tp2_hit and low <= pos.tp2:
                exit_price = pos.tp2 * (1 + SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "TP2", timestamp, qty=pos.tp2_qty)
                pos.tp2_hit = True
                pos.stop_loss = min(pos.stop_loss, pos.tp1)

            if pos.tp2_hit and not pos.tp3_hit and low <= pos.tp3:
                exit_price = pos.tp3 * (1 + SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "TP3", timestamp, qty=pos.tp3_qty)
                pos.tp3_hit = True

            if high >= pos.stop_loss and symbol in self.positions:
                exit_price = pos.stop_loss * (1 + SLIPPAGE_BPS / 10000)
                self.close_position(symbol, exit_price, "STOP_LOSS", timestamp)

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
            risk_amount=pos.risk_amount,
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
