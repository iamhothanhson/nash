from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.exchange_client import BinanceExchangeClient, LotConstraints


def _render_exchange_info_body() -> str:
    payload = {
        "symbols": [
            {
                "symbol": "RENDERUSDT",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.1",
                        "minQty": "0.1",
                        "maxQty": "1000000",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "stepSize": "0.1",
                        "minQty": "0.1",
                        "maxQty": "1000000",
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }
    return json.dumps(payload)


def _fet_exchange_info_body() -> str:
    payload = {
        "symbols": [
            {
                "symbol": "FETUSDT",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "1",
                        "minQty": "1",
                        "maxQty": "1000000",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "stepSize": "1",
                        "minQty": "1",
                        "maxQty": "1000000",
                    },
                    {"filterType": "MIN_NOTIONAL", "notional": "5"},
                ],
            }
        ]
    }
    return json.dumps(payload)


def _tao_demo_exchange_info_body() -> str:
    payload = {
        "symbols": [
            {
                "symbol": "TAOUSDT",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "stepSize": "0.001",
                        "minQty": "0.001",
                        "maxQty": "300",
                    },
                    {
                        "filterType": "MARKET_LOT_SIZE",
                        "stepSize": "0.001",
                        "minQty": "0.001",
                        "maxQty": "10",
                    },
                ],
            }
        ]
    }
    return json.dumps(payload)


def test_normalize_order_qty_caps_to_market_lot_max() -> None:
    client = BinanceExchangeClient(
        base_url="https://demo-fapi.binance.com",
        api_key="k",
        api_secret="s",
    )
    class _Resp:
        def read(self) -> bytes:
            return _tao_demo_exchange_info_body().encode()

    class _Ctx:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *args: object) -> None:
            return None

    with patch("execution.exchange_client.urlopen", return_value=_Ctx()):
        cons = client.market_lot_constraints("TAOUSDT")
        assert cons == LotConstraints(step=0.001, min_qty=0.001, max_qty=10.0)
        assert client.normalize_qty("TAOUSDT", 28.809332235589697) == 10.0


def test_normalize_entry_qty_does_not_bump_for_min_notional() -> None:
    client = BinanceExchangeClient(
        base_url="https://fapi.binance.com",
        api_key="k",
        api_secret="s",
    )

    class _Resp:
        def read(self) -> bytes:
            return _fet_exchange_info_body().encode()

    class _Ctx:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *args: object) -> None:
            return None

    with patch("execution.exchange_client.urlopen", return_value=_Ctx()):
        # 14 * 0.35 = 4.9 USDT < 5 min notional — no bump; lot step only
        qty = client.normalize_entry_qty("FETUSDT", 14.0, entry_price=0.35)
        assert qty == 14.0


def test_normalize_entry_qty_rounds_render_lot_without_min_notional_bump() -> None:
    client = BinanceExchangeClient(
        base_url="https://fapi.binance.com",
        api_key="k",
        api_secret="s",
    )

    class _Resp:
        def read(self) -> bytes:
            return _render_exchange_info_body().encode()

    class _Ctx:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *args: object) -> None:
            return None

    with patch("execution.exchange_client.urlopen", return_value=_Ctx()):
        qty = client.normalize_entry_qty("RENDERUSDT", 2.1, entry_price=2.38)
        assert qty == 2.1
