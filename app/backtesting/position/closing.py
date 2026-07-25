from __future__ import annotations

from datetime import datetime
from typing import Any

from dataclasses import asdict

from backtesting.config import FEES
from backtesting.models import BacktestPosition, BacktestTrade
from backtesting.position.builder import build_trade
from analysis.collect_position_metrics import update_entry_result
from position.archive import archive_position


class Closing:
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

        trade = build_trade(pos, close_qty, exit_price, exit_reason, timestamp, FEES)
        self.trades.append(trade)

        self._update_position(pos, trade)
        self._update_account(trade)

        if pos.remaining_qty <= 0:
            self._finalize_position(symbol, pos, timestamp, exit_reason)

        return trade


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
        self.account.available_balance += pos.margin_usdt

    @staticmethod
    def _update_position(pos: BacktestPosition, trade: BacktestTrade) -> None:
        pos.remaining_qty -= trade.qty
        pos.realized_pnl += trade.net_pnl

    def _update_account(self, trade: BacktestTrade) -> None:
        self.account.apply_realized_pnl(trade.net_pnl)

    @staticmethod
    def _update_runtime_result(pos: BacktestPosition, reason: str) -> None:
        margin = pos.margin_usdt or (pos.entry * pos.initial_qty)
        pnl_pct = (pos.realized_pnl / margin * 100) if margin else 0.0
        result = "WIN" if pos.realized_pnl >= 0 else "LOSS"
        update_entry_result(pos.position_id, result, pnl_pct, pos.realized_pnl, reason)
