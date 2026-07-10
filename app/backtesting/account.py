from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass
class BacktestAccountState:
    wallet_balance: Decimal
    available_balance: Decimal
    margin_balance: Decimal
    unrealized_pnl: Decimal


class BacktestAccountService:
    def __init__(self, initial_balance: float = 100) -> None:
        if initial_balance <= 0:
            raise ValueError("initial_balance must be greater than zero")

        self.wallet_balance = initial_balance
        self.available_balance = initial_balance
        self.unrealized_pnl = 0.0

    @property
    def margin_balance(self) -> float:
        return self.wallet_balance + self.unrealized_pnl

    def get_account_state(self) -> BacktestAccountState:
        return BacktestAccountState(
            wallet_balance=Decimal(str(self.wallet_balance)),
            available_balance=Decimal(str(self.available_balance)),
            margin_balance=Decimal(str(self.margin_balance)),
            unrealized_pnl=Decimal(str(self.unrealized_pnl)),
        )

    def apply_realized_pnl(self, pnl: float) -> None:
        self.wallet_balance += pnl
        self.available_balance += pnl

    def set_unrealized_pnl(self, pnl: float) -> None:
        self.unrealized_pnl = pnl