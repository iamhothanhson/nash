from __future__ import annotations

from datetime import datetime
from typing import Any

from app.core.enums import TrailType
from backtesting.models import BacktestPosition
from backtesting.position.utils import apply_slippage


class Exit:
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

            exit_price = apply_slippage(tp.price, is_long)

            self.close_position(
                symbol=symbol,
                exit_price=exit_price,
                exit_reason=f"TP{tp.level}",
                timestamp=timestamp,
                qty=tp.qty,
            )

            tp.hit = True

            if tp.trail_type == TrailType.BREAK_EVEN:
                trail_price = pos.entry
                if is_long:
                    pos.stop_loss = max(pos.stop_loss, trail_price)
                else:
                    pos.stop_loss = min(pos.stop_loss, trail_price)

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
