from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.error import URLError
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.exchange_client import BinanceExchangeClient


def test_sync_server_time_sets_offset() -> None:
    client = BinanceExchangeClient(
        base_url="https://fapi.binance.com",
        api_key="k",
        api_secret="s",
    )
    client._time_offset_ms = 0
    client._time_sync_mono = 0.0
    local = int(time.time() * 1000)
    server = local + 2500

    class _Resp:
        def read(self) -> bytes:
            return json.dumps({"serverTime": server}).encode()

    class _Ctx:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *args: object) -> None:
            return None

    with patch("execution.exchange_client.urlopen", return_value=_Ctx()):
        offset = client.sync_server_time(force=True)
    assert abs(offset - 2500) < 50


def test_sync_server_time_retries_transient_url_error() -> None:
    client = BinanceExchangeClient(
        base_url="https://fapi.binance.com",
        api_key="k",
        api_secret="s",
    )
    client._TIME_SYNC_RETRY_SLEEP_SEC = 0.0
    local = int(time.time() * 1000)
    server = local + 100

    class _Resp:
        def read(self) -> bytes:
            return json.dumps({"serverTime": server}).encode()

    class _Ctx:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *args: object) -> None:
            return None

    calls = {"n": 0}

    def _urlopen(*_args: object, **_kwargs: object) -> _Ctx:
        calls["n"] += 1
        if calls["n"] == 1:
            raise URLError("connection reset")
        return _Ctx()

    with patch("execution.exchange_client.urlopen", side_effect=_urlopen):
        offset = client.sync_server_time(force=True)
    assert calls["n"] == 2
    assert abs(offset - 100) < 50
    ts0 = client._request_timestamp_ms()
    assert ts0 >= server - 50
    time.sleep(0.05)
    ts1 = client._request_timestamp_ms()
    assert ts1 >= ts0
