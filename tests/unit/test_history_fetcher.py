from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd
import pytest

from marketplace import fetcher


@pytest.mark.unit
def test_testnet_auto_fetch_false_calls_live_demo_klines(monkeypatch) -> None:
    class _Settings:
        DATA_SOURCE = "testnet"
        MODE = "backtest"
        HISTORY_AUTO_FETCH = False

    monkeypatch.setattr(fetcher, "settings", _Settings())

    with patch(
        "marketplace.fetcher.get_ohlcv",
        return_value=[
            {
                "time": 1_000_000,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            }
        ],
    ) as get_ohlcv:
        frame = fetcher.fetch_market_data("TAOUSDT", "15m", limit=1)
        get_ohlcv.assert_called_once()

    assert len(frame) == 1


@pytest.mark.unit
def test_testnet_auto_fetch_false_blocks_history_csv_download(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(fetcher, "_HISTORY_DATA_DIR", tmp_path)

    class _Settings:
        DATA_SOURCE = "testnet"
        MODE = "backtest"
        HISTORY_AUTO_FETCH = False
        BACKTEST_HISTORY_ANCHOR_LATEST = True
        BACKTEST_END = ""

    monkeypatch.setattr(fetcher, "settings", _Settings())

    with patch(
        "marketplace.fetcher.get_ohlcv",
        return_value=[
            {
                "time": int(datetime.now(timezone.utc).timestamp() * 1000) - 900_000,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 10.0,
            }
        ],
    ) as get_ohlcv:
        with patch("marketplace.fetcher._fetch_provider_range") as provider_fetch:
            frame = fetcher.fetch_market_data_range("TAOUSDT", "15m", days=7, force_fetch=True)
            provider_fetch.assert_not_called()
            get_ohlcv.assert_called()

    assert len(frame) == 1
    assert not (tmp_path / "TAOUSDT_15m.csv").exists()


@pytest.mark.unit
def test_history_auto_fetch_false_uses_csv_without_network(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(fetcher, "_HISTORY_DATA_DIR", tmp_path)
    pd.DataFrame(
        {
            "time": [1_000_000, 1_900_000],
            "open": [100.0, 101.0],
            "high": [101.0, 102.0],
            "low": [99.0, 100.0],
            "close": [100.5, 101.5],
            "volume": [10.0, 11.0],
        }
    ).to_csv(tmp_path / "TAOUSDT_15m.csv", index=False)

    class _Settings:
        DATA_SOURCE = "history"
        MODE = "backtest"
        HISTORY_AUTO_FETCH = False
        BACKTEST_HISTORY_ANCHOR_LATEST = True
        BACKTEST_END = ""

    monkeypatch.setattr(fetcher, "settings", _Settings())

    with patch("marketplace.fetcher.get_ohlcv") as get_ohlcv:
        frame = fetcher.fetch_market_data_range("TAOUSDT", "15m", days=3650, force_fetch=True)
        get_ohlcv.assert_not_called()

    assert len(frame) == 2


@pytest.mark.unit
def test_history_auto_fetch_true_force_fetch_backfills_cache(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(fetcher, "_HISTORY_DATA_DIR", tmp_path)

    class _Settings:
        DATA_SOURCE = "testnet"
        MODE = "backtest"
        HISTORY_AUTO_FETCH = True
        BACKTEST_HISTORY_ANCHOR_LATEST = True
        BACKTEST_END = ""

    monkeypatch.setattr(fetcher, "settings", _Settings())

    fetched = pd.DataFrame(
        {
            "time": [1_000_000, 1_900_000],
            "open": [50.0, 51.0],
            "high": [51.0, 52.0],
            "low": [49.0, 50.0],
            "close": [50.5, 51.5],
            "volume": [5.0, 6.0],
        }
    )

    with patch("marketplace.fetcher._fetch_provider_range", return_value=fetched) as provider_fetch:
        frame = fetcher.fetch_market_data_range("TAOUSDT", "15m", days=3650, force_fetch=True)
        provider_fetch.assert_called_once()

    assert len(frame) == 2
    assert (tmp_path / "TAOUSDT_15m.csv").exists()
