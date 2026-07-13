from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import requests

from core.rounding import round_step
from config import settings
from exchange.exceptions import BinanceOrderError


class BinanceFuturesClient:

    def __init__(self) -> None:
        self._session = requests.Session()
        self._symbol_cache: dict[str, dict[str, Any]] = {}

    @property
    def base_url(self) -> str:
        if settings.MODE == "live":
            return settings.BINANCE_FAPI_LIVE_HOST
        return settings.BINANCE_FAPI_DEMO_HOST

    @property
    def api_key(self) -> str:
        if settings.MODE == "live":
            return settings.BINANCE_API_KEY
        return settings.BINANCE_TESTNET_API_KEY

    @property
    def secret(self) -> str:
        if settings.MODE == "live":
            return settings.BINANCE_SECRET
        return settings.BINANCE_TESTNET_SECRET

    # ------------------------------------------------------------------
    # signing & request helpers
    # ------------------------------------------------------------------

    def _sign(self, params: dict[str, Any]) -> str:
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        return hmac.new(
            self.secret.encode("utf-8"),
            query.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        signed: bool = True,
    ) -> Any:
        url = f"{self.base_url}/{path}"
        params = dict(params or {})
        if signed:
            params["timestamp"] = int(time.time() * 1000)
            params["recvWindow"] = settings.BINANCE_RECV_WINDOW_MS
            params["signature"] = self._sign(params)
        headers = {"X-MBX-APIKEY": self.api_key} if signed else {}
        resp = self._session.request(method, url, params=params, headers=headers, timeout=10)
        if resp.status_code != 200:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise BinanceOrderError(
                code=body.get("code", -1),
                msg=body.get("msg", resp.text),
            )
        return resp.json()

    def get_price(self, symbol: str) -> float:
        try:
            resp = self.request(
                "GET", "fapi/v1/ticker/price",
                {"symbol": symbol},
                signed=False,
            )
            return float(resp.get("price", 0.0))
        except Exception:
            return 0.0

    # ------------------------------------------------------------------
    # symbol info / filters
    # ------------------------------------------------------------------

    def _load_symbol_info(self, symbol: str) -> dict[str, Any]:
        if symbol not in self._symbol_cache:
            raw = self.request("GET", "fapi/v1/exchangeInfo", {"symbol": symbol}, signed=False)
            for s in raw.get("symbols", []):
                if s["symbol"] == symbol:
                    self._symbol_cache[symbol] = s
                    break
        return self._symbol_cache.get(symbol, {})

    def price_tick_size(self, symbol: str) -> float:
        info = self._load_symbol_info(symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "PRICE_FILTER":
                return float(f["tickSize"])
        return 0.01

    def lot_size_step(self, symbol: str) -> float:
        info = self._load_symbol_info(symbol)
        for f in info.get("filters", []):
            if f["filterType"] == "LOT_SIZE":
                return float(f["stepSize"])
        return 0.001

    def normalize_price(self, symbol: str, price: float) -> float:
        return round_step(price, self.price_tick_size(symbol))

    def normalize_qty(self, symbol: str, qty: float) -> float:
        return round_step(qty, self.lot_size_step(symbol))

    def normalize_stop_price(self, symbol: str, price: float) -> float:
        return self.normalize_price(symbol, price)

    # ------------------------------------------------------------------
    # account / market data
    # ------------------------------------------------------------------

    def get_account(self) -> dict[str, Any]:
        return self.request("GET", "fapi/v2/account")

    def get_positions(self) -> list[dict[str, Any]]:
        return self.get_account().get("positions", [])

    def get_balance(self, asset: str = "USDT") -> float:
        for bal in self.get_account().get("assets", []):
            if bal["asset"] == asset:
                return float(bal["walletBalance"])
        return 0.0

    def get_mark_price(self, symbol: str) -> float:
        resp = self.request("GET", "fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)
        return float(resp.get("markPrice", 0.0))

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
        return self.request(
            "GET", "fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
            signed=False,
        )

    # ------------------------------------------------------------------
    # order placement
    # ------------------------------------------------------------------

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "fapi/v1/order", params)

    def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return self.request("POST", "fapi/v1/order", {"symbol": symbol, "orderId": order_id})

    def cancel_all_orders(self, symbol: str) -> list[dict[str, Any]]:
        return self.request("DELETE", "fapi/v1/allOpenOrders", {"symbol": symbol})

    def cancel_futures_stop_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return self.cancel_order(symbol, order_id)

    def create_conditional_stop_market_order(
        self,
        symbol: str,
        side: str,
        stop_price: float,
        quantity: float | None = None,
        close_position: bool = False,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": "STOP_MARKET",
            "stopPrice": stop_price,
            "workingType": "MARK_PRICE",
        }
        if close_position:
            params["closePosition"] = "true"
        elif quantity is not None and quantity > 0:
            params["quantity"] = quantity
        if position_side:
            params["positionSide"] = position_side
        return self.place_order(params)

