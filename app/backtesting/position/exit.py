from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.enums import TrailType
from backtesting.models import BacktestPosition, TakeProfit
from backtesting.position.utils import apply_slippage
from .closing import Closing


class Exit(Closing):
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

            self._update_trailing_tp(pos, tp)

            if not self._tp_touched(tp, high, low, is_long):
                continue

            self._hit_take_profit(
                pos=pos,
                tp=tp,
                symbol=symbol,
                is_long=is_long,
                timestamp=timestamp,
            )

    def _update_trailing_tp(
        self,
        pos: BacktestPosition,
        tp: TakeProfit,
    ) -> None:
        if tp.level != 2:
            return

        if not pos.take_profits[0].hit:
            return

        if tp.trail_type != TrailType.ATR:
            return

        self._update_tp2_price(pos, tp)

    def _update_tp2_price(
        self,
        pos: BacktestPosition,
        tp: Any,
    ) -> None:
        if tp.atr_value <= 0:
            return
        atr_mult = tp.atr_multiplier or 2.0
        if pos.direction == "LONG":
            tp.price = pos.highest_price - tp.atr_value * atr_mult
        else:
            tp.price = pos.lowest_price + tp.atr_value * atr_mult

    def _tp_touched(
        self,
        tp: TakeProfit,
        high: float,
        low: float,
        is_long: bool,
    ) -> bool:
        return high >= tp.price if is_long else low <= tp.price

    def _hit_take_profit(
        self,
        pos: BacktestPosition,
        tp: TakeProfit,
        symbol: str,
        is_long: bool,
        timestamp: datetime,
    ) -> None:
        self.close_position(
            symbol=symbol,
            exit_price=apply_slippage(tp.price, is_long),
            exit_reason=f"TP{tp.level}",
            timestamp=timestamp,
            qty=tp.qty,
        )

        tp.hit = True

        if tp.trail_type == TrailType.BREAK_EVEN:
            self._move_stop_to_break_even(pos, is_long)

    def _move_stop_to_break_even(
        self,
        pos: BacktestPosition,
        is_long: bool,
    ) -> None:
        if is_long:
            pos.stop_loss = max(pos.stop_loss, pos.entry)
        else:
            pos.stop_loss = min(pos.stop_loss, pos.entry)

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

        exit_price = apply_slippage(pos.stop_loss, is_long)

        self.close_position(
            symbol=symbol,
            exit_price=exit_price,
            exit_reason="STOP_LOSS",
            timestamp=timestamp,
        )
