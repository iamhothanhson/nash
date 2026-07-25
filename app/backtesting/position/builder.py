from __future__ import annotations

from datetime import datetime

from app.core.enums import TrailType
from backtesting.models import BacktestPosition, BacktestTrade, TakeProfit
from backtesting.position.utils import calculate_pnl
from order_planner.models import OrderPlan


def build_position(
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
        take_profits=[
            TakeProfit(level=1, price=order_plan.tp1, qty=order_plan.tp1_qty, pct=order_plan.tp1_pct, trail_type=TrailType.BREAK_EVEN),
            TakeProfit(level=2, price=order_plan.tp2, qty=order_plan.tp2_qty, pct=order_plan.tp2_pct, trail_type=TrailType.ATR),
            TakeProfit(level=3, price=order_plan.tp3, qty=order_plan.tp3_qty, pct=order_plan.tp3_pct),
        ],
        balance_usdt=wallet_balance,
        opened=timestamp,
        status="Open",
    )


def build_trade(
    pos: BacktestPosition,
    qty: float,
    exit_price: float,
    reason: str,
    timestamp: datetime,
    fee_rate: float,
) -> BacktestTrade:
    pnl = calculate_pnl(pos, qty, exit_price)
    fee = qty * exit_price * fee_rate
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
