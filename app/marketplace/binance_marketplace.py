from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd


class BinanceClient:
    def get_klines(self, *args: Any, **kwargs: Any) -> list[list[Any]]:
        return []

    def get_price(self, *args: Any, **kwargs: Any) -> float:
        return 0.0

    def get_symbol_info(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def get_account(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        return {}

    def get_positions(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []


class BinanceMarketplace:

    def __init__(self, client: BinanceClient | None = None):
        self.client = client or BinanceClient()
        self.history_dir = Path(__file__).resolve().parents[1] / "history_data"

    def get_market_data(
        self,
        symbol: str,
    ) -> dict[str, pd.DataFrame]:
        return {
            "5m": self._get_ohlcv(symbol, "5m"),
            "15m": self._get_ohlcv(symbol, "15m"),
            "1h": self._get_ohlcv(symbol, "1h"),
        }

    def _get_ohlcv(
        self,
        symbol: str,
        interval: str,
        limit: int = 300,
    ) -> pd.DataFrame:
        history_file = self.history_dir / f"{symbol}_{interval}.csv"
        if history_file.exists():
            df = pd.read_csv(history_file)
            if {"open", "high", "low", "close", "volume"}.issubset(df.columns):
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)

        candles = self.client.get_klines(
            symbol=symbol,
            interval=interval,
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