from __future__ import annotations

from dataclasses import dataclass

from exchange.client import BinanceFuturesClient


@dataclass(frozen=True, slots=True)
class AccountState:
    futures_account_balance: float   # used for risk sizing
    available_balance: float         # used to check if trade can open
    total_margin_used: float
    unrealized_pnl: float


class AccountService:

    def __init__(self, client: BinanceFuturesClient | None = None):
        self._client = client

    def _get_client(self) -> BinanceFuturesClient:
        if self._client is None:
            self._client = BinanceFuturesClient()
        return self._client

    def get_account_state(self) -> AccountState:
        account = self._get_client().get_account()

        futures_account_balance = float(account.get("totalWalletBalance", 0))
        available_balance = float(account.get("availableBalance", 0))
        total_margin_used = float(account.get("totalInitialMargin", 0))
        unrealized_pnl = float(account.get("totalUnrealizedProfit", 0))

        return AccountState(
            futures_account_balance=futures_account_balance,
            available_balance=available_balance,
            total_margin_used=total_margin_used,
            unrealized_pnl=unrealized_pnl,
        )