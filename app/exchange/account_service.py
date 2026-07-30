from __future__ import annotations
from exchange.models import AccountState
from exchange.client import BinanceFuturesClient

class AccountService:

    def __init__(self, client: BinanceFuturesClient | None = None):
        self._client = client

    def _get_client(self) -> BinanceFuturesClient:
        if self._client is None:
            self._client = BinanceFuturesClient()
        return self._client

    def get_account_state(self) -> AccountState:
        account = self._get_client().get_account()

        wallet_balance = float(account.get("totalWalletBalance", 0))
        available_balance = float(account.get("availableBalance", 0))
        unrealized_pnl = float(account.get("totalUnrealizedProfit", 0))
        margin_balance = wallet_balance + unrealized_pnl

        return AccountState(
            wallet_balance=wallet_balance,
            available_balance=available_balance,
            margin_balance=margin_balance,
            unrealized_pnl=unrealized_pnl,
        )