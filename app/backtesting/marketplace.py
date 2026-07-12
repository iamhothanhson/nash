from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd


class HistoricalMarketplace:
    def __init__(
        self,
        data: dict[str, dict[str, pd.DataFrame]] | None = None,
    ):
        self.data = data or {}

    @classmethod
    def from_csv_dir(cls, history_dir: str | Path) -> HistoricalMarketplace:
        history_dir = Path(history_dir)
        data: dict[str, dict[str, pd.DataFrame]] = {}

        for csv_path in sorted(history_dir.glob("*.csv")):
            parts = csv_path.stem.split("_")
            symbol = parts[0] if parts[0].endswith("USDT") else parts[0] + "USDT"
            interval = parts[1] if len(parts) > 1 else "15m"
            interval_map = {"5m": "5m", "15m": "15m", "1h": "1h"}
            interval = interval_map.get(interval, "15m")

            raw = pd.read_csv(csv_path)
            if "time" in raw.columns:
                raw["datetime"] = pd.to_datetime(raw["time"], unit="ms")
            elif "open_time" in raw.columns:
                raw["datetime"] = pd.to_datetime(raw["open_time"], unit="ms")
            else:
                raw["datetime"] = pd.date_range(
                    end=datetime.now(), periods=len(raw), freq=interval.replace("m", "min")
                )

            raw.set_index("datetime", inplace=True)
            raw.index.name = "datetime"
            for col in ["open", "high", "low", "close", "volume"]:
                raw[col] = pd.to_numeric(raw[col], errors="coerce")
            df = raw[["open", "high", "low", "close", "volume"]]

            data.setdefault(symbol, {})[interval] = df

        return cls(data=data)

    def get_market_data(
        self,
        symbol: str,
        up_to: Any | None = None,
        lookback: int | None = None,
    ) -> dict[str, pd.DataFrame] | None:
        symbol_data = self.data.get(symbol)
        if symbol_data is None:
            return None
        if up_to is None:
            return symbol_data
        result: dict[str, pd.DataFrame] = {}
        for tf, df in symbol_data.items():
            idx = df.index.get_indexer([up_to], method="nearest")[0]
            if idx < 0:
                return None
            start = max(0, idx - lookback + 1) if lookback is not None else 0
            result[tf] = df.iloc[start: idx + 1]
        return result

    def get_candle(self, symbol: str, timestamp: Any) -> dict[str, Any] | None:
        symbol_data = self.data.get(symbol)
        if symbol_data is None:
            return None
        for df in symbol_data.values():
            if timestamp in df.index:
                row = df.loc[timestamp]
                return {
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
        return None
