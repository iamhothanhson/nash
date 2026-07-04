from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.exchange_client import BinanceExchangeClient, BinanceOrderError
from execution.position_mode import (
    normalize_position_mode_setting,
    position_side_for_direction,
    position_side_for_entry,
    position_side_for_reduce_order,
)


def test_normalize_position_mode_toggle_values() -> None:
    assert normalize_position_mode_setting("oneway") == "oneway"
    assert normalize_position_mode_setting("one-way") == "oneway"
    assert normalize_position_mode_setting("hedge") == "hedge"
    assert normalize_position_mode_setting("auto") == "auto"
    assert normalize_position_mode_setting("hedge | oneway | auto") == "hedge"


def test_market_order_omits_position_side_in_oneway_mode() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "oneway"
    with patch.object(client, "_normalize_order_qty", return_value=1.0):
        with patch.object(client, "_signed_request", return_value={"orderId": 1}) as req:
            client.create_market_order("BTCUSDT", "BUY", 1.0, position_side="LONG")
            payload = req.call_args[0][2]
            assert "positionSide" not in payload


def test_position_side_mapping() -> None:
    assert position_side_for_entry("BUY") == "LONG"
    assert position_side_for_entry("SELL") == "SHORT"
    assert position_side_for_reduce_order("SELL") == "LONG"
    assert position_side_for_reduce_order("BUY") == "SHORT"
    assert position_side_for_direction("LONG") == "LONG"


def test_stop_order_omits_reduce_only_in_hedge_mode() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "hedge"
    with patch.object(client, "_normalize_order_qty", return_value=1.0):
        with patch.object(client, "_normalize_price_to_tick", return_value=100.0):
            with patch.object(client, "_cancel_all_open_algo_orders_safe"):
                with patch.object(client, "_signed_request", return_value={"algoId": 99}) as req:
                    client.create_reduce_only_stop_market_order(
                        "BTCUSDT", "SELL", 1.0, 95.0, position_side="LONG"
                    )
                    payload = req.call_args[0][2]
                    assert payload.get("positionSide") == "LONG"
                    assert "reduceOnly" not in payload


def test_stop_order_includes_reduce_only_in_oneway_mode() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "oneway"
    with patch.object(client, "_normalize_order_qty", return_value=1.0):
        with patch.object(client, "_normalize_price_to_tick", return_value=100.0):
            with patch.object(client, "_cancel_all_open_algo_orders_safe"):
                with patch.object(client, "_signed_request", return_value={"algoId": 99}) as req:
                    client.create_reduce_only_stop_market_order("BTCUSDT", "SELL", 1.0, 95.0)
                    payload = req.call_args[0][2]
                    assert payload.get("reduceOnly") == "true"
                    assert "positionSide" not in payload


def test_has_open_position_size_checks_each_hedge_leg() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "hedge"
    with patch.object(client, "get_position_amount", side_effect=lambda sym, leg=None: 0.035 if leg == "LONG" else 0.0):
        assert client.has_open_position_size("TAOUSDT") is True
        assert "LONG=0.03500000" in client.open_position_summary("TAOUSDT")


def test_market_order_retries_without_position_side_on_mismatch() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "hedge"
    mismatch = BinanceOrderError(
        status_code=400,
        code=-4061,
        msg="Order's position side does not match user's setting.",
        request_params={},
    )
    ok = {"orderId": 42}
    with patch.object(client, "_normalize_order_qty", return_value=1.0):
        with patch.object(client, "exchange_dual_side_enabled", return_value=False):
            with patch.object(client, "_signed_request", side_effect=[mismatch, ok]) as req:
                out = client.create_market_order("TAOUSDT", "SELL", 1.0)
                assert out["orderId"] == 42
                assert req.call_count == 2
                retry_payload = req.call_args_list[1][0][2]
                assert "positionSide" not in retry_payload
                assert retry_payload["side"] == "SELL"
                assert client.use_hedge_position_side() is True
                assert client._hedge_mode_cached is False


def test_market_order_retries_with_position_side_when_env_oneway_exchange_hedge() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "oneway"
    mismatch = BinanceOrderError(
        status_code=400,
        code=-4061,
        msg="Order's position side does not match user's setting.",
        request_params={},
    )
    ok = {"orderId": 42}
    with patch.object(client, "_normalize_order_qty", return_value=1.0):
        with patch.object(client, "exchange_dual_side_enabled", return_value=True):
            with patch.object(client, "_signed_request", side_effect=[mismatch, ok]) as req:
                out = client.create_market_order("TAOUSDT", "SELL", 1.0)
                assert out["orderId"] == 42
                retry_payload = req.call_args_list[1][0][2]
                assert retry_payload.get("positionSide") == "SHORT"


def test_market_order_includes_position_side_in_hedge_mode() -> None:
    client = BinanceExchangeClient(base_url="https://example.com", api_key="k", api_secret="s")
    client._position_mode_setting = "hedge"
    with patch.object(client, "_normalize_order_qty", return_value=1.0):
        with patch.object(client, "_signed_request", return_value={"orderId": 1}) as req:
            client.create_market_order("BTCUSDT", "BUY", 1.0, position_side="LONG")
            payload = req.call_args[0][2]
            assert payload["positionSide"] == "LONG"
            assert payload["side"] == "BUY"
