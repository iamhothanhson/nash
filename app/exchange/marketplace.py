from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from app.exchange.client import BinanceFuturesClient


class BinanceMarketplace:

    def __init__(self, client: BinanceFuturesClient | None = None):
        self.client = client or BinanceFuturesClient()

    def get_market_data(
        self,
        symbol: str,
    ) -> dict[str, pd.DataFrame]:
        return {
            "5m": self.get_candle(symbol, "5m"),
            "15m": self.get_candle(symbol, "15m"),
            "1h": self.get_candle(symbol, "1h"),
        }

    def get_candle(
        self,
        symbol: str,
        timeframe: str,
        limit: int = 300,
    ) -> pd.DataFrame:

        candles = self.client.get_klines(
            symbol=symbol,
            interval=timeframe,
            limit=limit,
        )

        if not candles:
            return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

        df = pd.DataFrame(
            candles,
            columns=[
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "close_time",
                "quote_asset_volume",
                "number_of_trades",
                "taker_buy_base_volume",
                "taker_buy_quote_volume",
                "ignore",
            ],
        )

        numeric_columns = [
            "open",
            "high",
            "low",
            "close",
            "volume",
        ]

        df[numeric_columns] = df[numeric_columns].astype(float)

        return df[
            [
                "open_time",
                "open",
                "high",
                "low",
                "close",
                "volume",
            ]
        ]

    def get_last_price(self, symbol: str) -> float:
        return float(self.client.get_price(symbol))

    def get_exchange_info(self, symbol: str) -> dict[str, Any]:
        return self.client.get_symbol_info(symbol)

    def get_account(self) -> dict[str, Any]:
        return self.client.get_account()

    def get_positions(self) -> list[dict[str, Any]]:
        return self.client.get_positions()