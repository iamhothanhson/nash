from __future__ import annotations

from typing import Any

from execution.exchange_client import BinanceExchangeClient


class ExchangeOrderGateway:
    """Build and submit exchange orders."""

    def __init__(self, exchange_client: BinanceExchangeClient) -> None:
        self.exchange_client = exchange_client

    def create_market_order(
        self, symbol: str, side: str, amount: float, *, position_side: str | None = None
    ) -> dict[str, Any]:
        return self.exchange_client.create_market_order(
            symbol, side, amount, position_side=position_side
        )

    def create_limit_order(self, symbol: str, side: str, amount: float, price: float) -> dict[str, Any]:
        # TODO: Support limit order endpoint/params with precision filters.
        raise NotImplementedError(
            f"Limit orders are not implemented yet ({symbol} {side} amount={amount} price={price})"
        )

    def create_reduce_only_market_order(
        self, symbol: str, side: str, amount: float, *, position_side: str | None = None
    ) -> dict[str, Any]:
        return self.exchange_client.create_reduce_only_market_order(
            symbol, side, amount, position_side=position_side
        )

    def create_reduce_only_limit_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        *,
        position_side: str | None = None,
    ) -> dict[str, Any]:
        return self.exchange_client.create_reduce_only_limit_order(
            symbol, side, amount, price, position_side=position_side
        )

    def create_stop_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        *,
        position_side: str | None = None,
    ) -> dict[str, Any]:
        return self.exchange_client.create_stop_market_order(
            symbol, side, amount, stop_price, position_side=position_side
        )

    def create_reduce_only_stop_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        *,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = True,
    ) -> dict[str, Any]:
        return self.exchange_client.create_reduce_only_stop_market_order(
            symbol,
            side,
            amount,
            stop_price,
            position_side=position_side,
            cancel_all_algo_orders=cancel_all_algo_orders,
        )

    def get_tp2_take_profit_market_algo_order(self, algo_id: int) -> dict[str, Any]:
        return self.exchange_client.get_tp2_take_profit_market_algo_order(algo_id)

    def create_conditional_take_profit_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        trigger_price: float,
        *,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = False,
    ) -> dict[str, Any]:
        return self.exchange_client.create_conditional_take_profit_market_order(
            symbol,
            side,
            amount,
            trigger_price,
            position_side=position_side,
            cancel_all_algo_orders=cancel_all_algo_orders,
        )

    def create_conditional_stop_market_order(
        self,
        symbol: str,
        side: str,
        stop_price: float,
        *,
        quantity: float | None = None,
        close_position: bool = False,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = True,
    ) -> dict[str, Any]:
        return self.exchange_client.create_conditional_stop_market_order(
            symbol,
            side,
            stop_price,
            quantity=quantity,
            close_position=close_position,
            position_side=position_side,
            cancel_all_algo_orders=cancel_all_algo_orders,
        )

    def cancel_futures_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return self.exchange_client.cancel_futures_order(symbol, order_id)
