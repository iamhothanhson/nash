from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any

import requests

from config import settings
from monitoring.logger import log
from order_planner.models import OrderPlan


class BinanceOrderError(Exception):
    def __init__(self, code: int, msg: str) -> None:
        self.code = code
        self.msg = msg
        super().__init__(f"[{code}] {msg}")


def _round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(round(value / step) * step, 8)


def _position_side(direction: str, *, hedge_mode: bool) -> str | None:
    if not hedge_mode:
        return None
    return "LONG" if direction.upper() == "LONG" else "SHORT"


class BinanceFuturesClient:

    def __init__(self) -> None:
        self._session = requests.Session()
        mode = settings.MODE
        if mode == "live":
            self.base_url = settings.BINANCE_FAPI_LIVE_HOST
            self.api_key = settings.BINANCE_API_KEY
            self.secret = settings.BINANCE_SECRET
        else:
            self.base_url = settings.BINANCE_FAPI_DEMO_HOST
            self.api_key = settings.BINANCE_TESTNET_API_KEY
            self.secret = settings.BINANCE_TESTNET_SECRET
        self._symbol_cache: dict[str, dict[str, Any]] = {}

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

    def _request(
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

    # ------------------------------------------------------------------
    # symbol info / filters
    # ------------------------------------------------------------------

    def _load_symbol_info(self, symbol: str) -> dict[str, Any]:
        if symbol not in self._symbol_cache:
            raw = self._request("GET", "fapi/v1/exchangeInfo", {"symbol": symbol}, signed=False)
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
        return _round_step(price, self.price_tick_size(symbol))

    def normalize_qty(self, symbol: str, qty: float) -> float:
        return _round_step(qty, self.lot_size_step(symbol))

    # ------------------------------------------------------------------
    # account / market data
    # ------------------------------------------------------------------

    def get_account(self) -> dict[str, Any]:
        return self._request("GET", "fapi/v2/account")

    def get_positions(self) -> list[dict[str, Any]]:
        return self.get_account().get("positions", [])

    def get_balance(self, asset: str = "USDT") -> float:
        for bal in self.get_account().get("assets", []):
            if bal["asset"] == asset:
                return float(bal["walletBalance"])
        return 0.0

    def get_mark_price(self, symbol: str) -> float:
        resp = self._request("GET", "fapi/v1/premiumIndex", {"symbol": symbol}, signed=False)
        return float(resp.get("markPrice", 0.0))

    def get_klines(self, symbol: str, interval: str, limit: int = 500) -> list[list[Any]]:
        return self._request(
            "GET", "fapi/v1/klines",
            {"symbol": symbol, "interval": interval, "limit": limit},
            signed=False,
        )

    # ------------------------------------------------------------------
    # order placement
    # ------------------------------------------------------------------

    def place_order(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "fapi/v1/order", params)

    def cancel_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        return self._request("POST", "fapi/v1/order", {"symbol": symbol, "orderId": order_id})

    def cancel_all_orders(self, symbol: str) -> list[dict[str, Any]]:
        return self._request("DELETE", "fapi/v1/allOpenOrders", {"symbol": symbol})


class Executor:
    """Places entry, stop-loss and take-profit orders on Binance Futures."""

    _client: BinanceFuturesClient | None = None

    TP1_FRAC = 0.50
    TP2_FRAC = 0.30

    # ------------------------------------------------------------------

    @classmethod
    def _get_client(cls) -> BinanceFuturesClient:
        if cls._client is None:
            cls._client = BinanceFuturesClient()
        return cls._client

    @classmethod
    def execute(cls, plan: OrderPlan) -> dict[str, Any]:
        if settings.MODE not in ("live", "demo"):
            log(f"[EXECUTOR] {plan.symbol} | skip (mode={settings.MODE})")
            return {"status": "skipped", "mode": settings.MODE}

        client = cls._get_client()
        sym = plan.symbol.strip().upper()
        direction = plan.direction.upper()
        hedge = settings.BINANCE_POSITION_MODE == "hedge"

        side = "BUY" if direction == "LONG" else "SELL"
        opp = "SELL" if side == "BUY" else "BUY"
        ps = _position_side(direction, hedge_mode=hedge)

        qty = client.normalize_qty(sym, plan.qty)
        if qty <= 0:
            raise BinanceOrderError(-1, f"Invalid quantity {plan.qty} after normalization")

        # ---- entry (MARKET) ----
        log(f"[EXECUTOR] {sym} | ENTER {side} qty={qty}")
        entry_resp = client.place_order({
            "symbol": sym,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newOrderRespType": "RESULT",
            **({"positionSide": ps} if ps else {}),
        })
        entry_id = entry_resp.get("orderId")
        fill_price = float(entry_resp.get("avgPrice", plan.entry))
        filled_qty = sum(float(f["qty"]) for f in entry_resp.get("fills", [])) or qty
        log(f"[EXECUTOR] {sym} | FILLED orderId={entry_id} price={fill_price} qty={filled_qty}")

        # ---- stop loss (STOP_MARKET, closePosition) ----
        sl_price = client.normalize_price(sym, plan.stop_loss)
        log(f"[EXECUTOR] {sym} | SL {opp} stopPrice={sl_price}")
        client.place_order({
            "symbol": sym,
            "side": opp,
            "type": "STOP_MARKET",
            "stopPrice": sl_price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
            **({"positionSide": ps} if ps else {}),
        })

        # ---- TP1 (TAKE_PROFIT_LIMIT) ----
        tp1_price = client.normalize_price(sym, plan.tp1)
        tp1_qty = client.normalize_qty(sym, filled_qty * cls.TP1_FRAC)
        if tp1_qty > 0:
            log(f"[EXECUTOR] {sym} | TP1 {opp} price={tp1_price} qty={tp1_qty}")
            client.place_order({
                "symbol": sym,
                "side": opp,
                "type": "TAKE_PROFIT_LIMIT",
                "price": tp1_price,
                "stopPrice": tp1_price,
                "quantity": tp1_qty,
                "timeInForce": "GTC",
                "workingType": "MARK_PRICE",
                **({"positionSide": ps} if ps else {}),
            })

        # ---- TP2 (TAKE_PROFIT_LIMIT) ----
        tp2_price = client.normalize_price(sym, plan.tp2)
        tp2_qty = client.normalize_qty(sym, filled_qty * cls.TP2_FRAC)
        if tp2_qty > 0:
            log(f"[EXECUTOR] {sym} | TP2 {opp} price={tp2_price} qty={tp2_qty}")
            client.place_order({
                "symbol": sym,
                "side": opp,
                "type": "TAKE_PROFIT_LIMIT",
                "price": tp2_price,
                "stopPrice": tp2_price,
                "quantity": tp2_qty,
                "timeInForce": "GTC",
                "workingType": "MARK_PRICE",
                **({"positionSide": ps} if ps else {}),
            })

        result = {
            "status": "placed",
            "symbol": sym,
            "direction": direction,
            "entry_order_id": entry_id,
            "entry_price": fill_price,
            "filled_qty": filled_qty,
        }
        log(f"[EXECUTOR] {sym} | Done — {result}")
        return result
