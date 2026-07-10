from __future__ import annotations

from typing import Any

import pandas as pd


class HistoricalMarketplace:
    def __init__(self):
        self.history_dir = Path(__file__).resolve().parents[2] / "data" / "history_data"

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
        timeframe: str,
        limit: int = 300,
    ) -> pd.DataFrame:
        history_file = self.history_dir / f"{symbol}_{timeframe}.csv"
        if history_file.exists():
            df = pd.read_csv(history_file)
            if {"open", "high", "low", "close", "volume"}.issubset(df.columns):
                for col in ["open", "high", "low", "close", "volume"]:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                return df[["open", "high", "low", "close", "volume"]].dropna().reset_index(drop=True)

        candles = self.client.get_klines(
            symbol=symbol,
            timeframe=timeframe,
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