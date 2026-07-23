from __future__ import annotations

from datetime import datetime
from typing import Any

from dataclasses import asdict

from backtesting.account import BacktestAccountService, BacktestAccountState
from backtesting.config import FEES, SLIPPAGE_BPS
from backtesting.models import BacktestPosition, BacktestTrade, EquityPoint
from position.archive import archive_position, save_runtime_position
from analysis.collect_position_metrics import update_entry_result


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
        is_long = pos.direction == "LONG"

        # tp_levels: (hit_attr, level_attr, reason, qty_attr, trailing_stop_price)
        levels = [
            ("tp1_hit", "tp1", "TP1", "tp1_qty", "entry"),
            ("tp2_hit", "tp2", "TP2", "tp2_qty", "tp1"),
            ("tp3_hit", "tp3", "TP3", "tp3_qty", None),
        ]
        for hit_attr, level_attr, reason, qty_attr, trail_to in levels:
            already_hit = getattr(pos, hit_attr)
            if already_hit:
                continue
            level = getattr(pos, level_attr)
            qty = getattr(pos, qty_attr)
            price_touched = (high >= level) if is_long else (low <= level)
            if not price_touched:
                continue
            slippage_mult = (1 - SLIPPAGE_BPS / 10000) if is_long else (1 + SLIPPAGE_BPS / 10000)
            exit_price = level * slippage_mult
            self.close_position(symbol, exit_price, reason, timestamp, qty=qty)
            setattr(pos, hit_attr, True)
            if trail_to:
                trail_price = getattr(pos, trail_to)
                pos.stop_loss = max(pos.stop_loss, trail_price) if is_long else min(pos.stop_loss, trail_price)

        # SL
        sl_hit = (low <= pos.stop_loss) if is_long else (high >= pos.stop_loss)
        if sl_hit and symbol in self.positions:
            slippage_mult = (1 - SLIPPAGE_BPS / 10000) if is_long else (1 + SLIPPAGE_BPS / 10000)
            exit_price = pos.stop_loss * slippage_mult
            self.close_position(symbol, exit_price, "STOP_LOSS", timestamp)

    def get_account_state(self) -> BacktestAccountState:
        return self.account.get_account_state()

    def open_position(self, symbol: str, direction: str, entry: float,
                      stop_loss: float, tp1: float, tp2: float, tp3: float,
                      qty: float, tp1_qty: float, tp2_qty: float, tp3_qty: float,
                      risk_amount: float, timestamp: datetime,
                      setup_type: str | None = None,
                      setup_score: float = 0.0,
                      position_id: str = "") -> BacktestPosition:
        leverage = 1.0
        margin_usdt = (qty * entry) / leverage

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
            margin_usdt=margin_usdt,
            position_id=position_id,
            setup_type=setup_type,
            setup_score=setup_score,
        )
        self.positions[symbol] = pos
        self.account.wallet_balance -= risk_amount
        self.account.available_balance -= risk_amount

        sl_pct = ((entry - stop_loss) / entry) * 100 if direction == "LONG" else ((stop_loss - entry) / entry) * 100
        tp1_pct = ((tp1 - entry) / entry) * 100 if direction == "LONG" else ((entry - tp1) / entry) * 100
        tp2_pct = ((tp2 - entry) / entry) * 100 if direction == "LONG" else ((entry - tp2) / entry) * 100
        tp3_pct = ((tp3 - entry) / entry) * 100 if direction == "LONG" else ((entry - tp3) / entry) * 100
        size_usdt = qty * entry

        save_runtime_position({
            "position_id": position_id,
            "status": "Open",
            "symbol": symbol,
            "side": direction,
            "strategy": "trend_following",
            "setup": setup_type or "",
            "size_usdt": round(size_usdt, 2),
            "margin_usdt": round(margin_usdt, 2),
            "entry": entry,
            "entry_qty": qty,
            "pos_side": None,
            "stop_loss": {"price": stop_loss, "percent": round(sl_pct, 2), "risk_usdt": risk_amount, "sl_order_id": None, "sl_hit": False},
            "take_profit": [
                {"tp1_partial_close": tp1_qty / qty * 100, "tp1_hit": False, "price": tp1, "percent": round(tp1_pct, 2), "tp1_order_id": None},
                {"tp2_partial_close": tp2_qty / qty * 100, "tp2_hit": False, "price": tp2, "percent": round(tp2_pct, 2), "tp2_order_id": None},
                {"tp3_partial_close": tp3_qty / qty * 100, "tp3_hit": False, "price": tp3, "percent": round(tp3_pct, 2), "tp3_order_id": None},
            ],
            "realized_pnl": 0.0,
            "pnl_usdt": 0.0,
            "exchange_pnl_usdt": None,
            "balance_usdt": self.account.wallet_balance,
            "closed_reason": None,
            "opened": timestamp.isoformat(),
            "closed": None,
        })

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
            archive_position(asdict(pos) | {"closed": timestamp.isoformat(), "exit_reason": exit_reason})
            margin = pos.margin_usdt or (pos.entry * pos.initial_qty)
            pnl_pct = (pos.realized_pnl / margin * 100) if margin else 0.0
            result = "WIN" if pos.realized_pnl >= 0 else "LOSS"
            update_entry_result(pos.position_id, result, pnl_pct, pos.realized_pnl, exit_reason)
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
