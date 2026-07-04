from __future__ import annotations

import hashlib
import hmac
import json
import logging
import math
import time
from dataclasses import dataclass
from typing import Any

from execution.position_mode import (
    normalize_position_mode_setting,
    position_side_for_entry,
    position_side_for_reduce_order,
)
from urllib.parse import urlencode
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

log = logging.getLogger(__name__)

try:
    from requests.exceptions import RequestException  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    RequestException = None  # type: ignore

try:
    from binance.exceptions import BinanceAPIException  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    BinanceAPIException = None  # type: ignore


def _sign_query(secret: str, query: str) -> str:
    return hmac.new(secret.encode("utf-8"), query.encode("utf-8"), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class LotConstraints:
    step: float
    min_qty: float
    max_qty: float


@dataclass(frozen=True)
class BinanceOrderError(Exception):
    """Structured Binance order failure used by execution layer."""

    status_code: int | None
    code: int | None
    msg: str
    request_params: dict[str, Any]
    raw_response: str | None = None

    def __str__(self) -> str:
        code_s = f"code={self.code}" if self.code is not None else "code=unknown"
        status_s = f"status={self.status_code}" if self.status_code is not None else "status=unknown"
        return f"{status_s} | {code_s} | msg={self.msg}"


class BinanceExchangeClient:
    """Exchange communication only: submit orders and query account."""

    def __init__(self, *, base_url: str, api_key: str, api_secret: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self._lot_size_cache: dict[str, LotConstraints] = {}
        self._min_notional_cache: dict[str, float] = {}
        self._price_tick_cache: dict[str, float] = {}
        self._hedge_mode_cached: bool | None = None
        self._time_offset_ms: int = 0
        self._time_sync_mono: float = 0.0
        self._server_time_anchor_ms: int = 0
        self._server_time_anchor_mono: float = 0.0
        self._TIME_SYNC_MAX_AGE_SEC = 30.0
        self._TIME_SYNC_URL_RETRIES = 3
        self._TIME_SYNC_RETRY_SLEEP_SEC = 1.0
        try:
            from config import settings

            raw_mode = getattr(settings, "BINANCE_POSITION_MODE", "auto")
            self._position_mode_setting = normalize_position_mode_setting(str(raw_mode))
            self._recv_window_ms = int(getattr(settings, "BINANCE_RECV_WINDOW_MS", 60000))
        except Exception as exc:
            log.warning(
                "[POSITION MODE] settings load failed (%s); defaulting to auto",
                exc,
            )
            self._position_mode_setting = "auto"
            self._recv_window_ms = 60000
        log.info(
            "[POSITION MODE] configured=%s orders_use_positionSide=%s",
            self._position_mode_setting,
            self.use_hedge_position_side(),
        )
        if self.api_key and self.api_secret:
            try:
                self.sync_server_time(force=True)
            except Exception as exc:
                log.warning("[TIME SYNC] initial sync failed | %s", exc)

    def position_mode_label(self) -> str:
        """Resolved mode string for logging: auto | hedge | oneway."""
        return str(self._position_mode_setting)

    def exchange_dual_side_enabled(self, *, use_cache: bool = True) -> bool:
        """Query Binance whether dual-side (hedge) position mode is active."""
        if use_cache and self._hedge_mode_cached is not None:
            return bool(self._hedge_mode_cached)
        try:
            data = self._signed_request("GET", "/fapi/v1/positionSide/dual", {})
            dual = bool(data.get("dualSidePosition")) if isinstance(data, dict) else False
        except Exception as exc:
            log.warning(
                "[POSITION MODE] GET /fapi/v1/positionSide/dual failed (%s); "
                "cannot verify hedge vs one-way from API.",
                exc,
            )
            return False
        self._hedge_mode_cached = dual
        return bool(dual)

    def use_hedge_position_side(self) -> bool:
        """True when orders must include positionSide LONG/SHORT (hedge mode)."""
        if self._position_mode_setting == "hedge":
            return True
        if self._position_mode_setting == "oneway":
            return False
        if self._hedge_mode_cached is not None:
            return bool(self._hedge_mode_cached)
        dual = self.exchange_dual_side_enabled()
        self._hedge_mode_cached = dual
        return bool(dual)

    def _invalidate_position_mode_cache(self) -> None:
        self._hedge_mode_cached = None

    @staticmethod
    def _is_position_side_mismatch_error(exc: BinanceOrderError) -> bool:
        if exc.code in (-4061, 4061):
            return True
        return "position side does not match" in str(exc.msg or "").lower()

    def _alt_hedge_after_position_side_mismatch(self, hedge: bool) -> bool:
        self._invalidate_position_mode_cache()
        if self._position_mode_setting == "auto":
            exchange_dual = self.exchange_dual_side_enabled(use_cache=False)
            if exchange_dual != hedge:
                return bool(exchange_dual)
        return not hedge

    def _post_order_with_position_mode_retry(
        self,
        path: str,
        build_payload: Any,
        *,
        side_for_leg: str | None = None,
        position_side: str | None = None,
        apply_env_hedge_force_on_first: bool = False,
    ) -> dict[str, Any]:
        hedge = self.use_hedge_position_side()
        if apply_env_hedge_force_on_first:
            payload = build_payload(hedge, apply_env_hedge_force=True)
        else:
            payload = build_payload(hedge)
        try:
            return self._signed_request("POST", path, payload)
        except BinanceOrderError as exc:
            if not self._is_position_side_mismatch_error(exc):
                raise
            first_ps = str(payload.get("positionSide", "")).upper() or "none"
            # -4061: flip whether we send positionSide (omitted → retry with LONG/SHORT leg).
            alt_hedge = not bool(payload.get("positionSide"))
            leg = position_side
            if alt_hedge and not leg and side_for_leg:
                leg = position_side_for_entry(side_for_leg)
            payload = build_payload(alt_hedge, position_side_override=leg)
            data = self._signed_request("POST", path, payload)
            self._hedge_mode_cached = alt_hedge
            retry_ps = str(payload.get("positionSide", "")).upper() or "none"
            log.warning(
                "[POSITION MODE] -4061 on %s | first=%s positionSide=%s | retry=%s positionSide=%s | "
                "BINANCE_POSITION_MODE=%s",
                path,
                "hedge" if hedge else "oneway",
                first_ps,
                "hedge" if alt_hedge else "oneway",
                retry_ps,
                self._position_mode_setting,
            )
            return data

    @staticmethod
    def _apply_position_side(payload: dict[str, Any], position_side: str | None, *, hedge: bool) -> dict[str, Any]:
        if hedge and position_side:
            out = dict(payload)
            out["positionSide"] = str(position_side).strip().upper()
            return out
        return payload

    @staticmethod
    def _apply_reduce_only(payload: dict[str, Any], *, hedge: bool) -> dict[str, Any]:
        """Binance hedge mode rejects reduceOnly; use positionSide + closing side instead."""
        if hedge:
            return dict(payload)
        out = dict(payload)
        out["reduceOnly"] = "true"
        return out

    def _urlopen_read_with_retry(
        self,
        request: Request,
        *,
        timeout: float = 15.0,
        retries: int | None = None,
    ) -> bytes:
        """GET helper with short backoff on transient URLError (e.g. connection reset)."""
        attempts = max(1, int(retries if retries is not None else self._TIME_SYNC_URL_RETRIES))
        last_exc: URLError | None = None
        for attempt in range(attempts):
            try:
                with urlopen(request, timeout=timeout) as response:
                    return response.read()
            except URLError as exc:
                last_exc = exc
                if attempt + 1 >= attempts:
                    raise
                delay = min(
                    float(self._TIME_SYNC_RETRY_SLEEP_SEC) * (2**attempt),
                    4.0,
                )
                time.sleep(delay)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("urlopen retry exhausted")

    def sync_server_time(self, *, force: bool = False) -> int:
        """Align signed request timestamps with Binance server clock; returns offset ms."""
        now_mono = time.monotonic()
        if (
            not force
            and self._server_time_anchor_mono > 0.0
            and now_mono - self._server_time_anchor_mono < self._TIME_SYNC_MAX_AGE_SEC
        ):
            return int(self._time_offset_ms)
        local_before = int(time.time() * 1000)
        url = f"{self.base_url}/fapi/v1/time"
        req = Request(url=url, method="GET")
        body = self._urlopen_read_with_retry(req, timeout=15.0).decode("utf-8")
        parsed = self._safe_json_decode(body)
        if not isinstance(parsed, dict):
            raise RuntimeError("Invalid /fapi/v1/time response")
        server_ms = int(parsed.get("serverTime", 0))
        if server_ms <= 0:
            raise RuntimeError("Missing serverTime from Binance")
        local_after = int(time.time() * 1000)
        local_est = (local_before + local_after) // 2
        offset = int(server_ms - local_est)
        self._time_offset_ms = offset
        self._time_sync_mono = now_mono
        self._server_time_anchor_ms = server_ms
        self._server_time_anchor_mono = now_mono
        if abs(offset) >= 1000:
            log.warning("[TIME SYNC] Binance clock offset %d ms (recvWindow=%d)", offset, self._recv_window_ms)
            try:
                from monitoring.logger import log as daily_log

                daily_log(
                    f"[TIME SYNC] Binance clock offset {offset} ms | "
                    f"recvWindow={int(self._recv_window_ms)} ms"
                )
            except Exception:
                pass
        return offset

    def _request_timestamp_ms(self) -> int:
        if self._server_time_anchor_mono > 0.0:
            elapsed_ms = int((time.monotonic() - self._server_time_anchor_mono) * 1000)
            return int(self._server_time_anchor_ms) + max(0, elapsed_ms)
        if self._time_sync_mono <= 0.0:
            try:
                self.sync_server_time(force=True)
            except Exception:
                pass
        if self._server_time_anchor_mono > 0.0:
            elapsed_ms = int((time.monotonic() - self._server_time_anchor_mono) * 1000)
            return int(self._server_time_anchor_ms) + max(0, elapsed_ms)
        return int(time.time() * 1000) + int(self._time_offset_ms)

    @staticmethod
    def _is_timestamp_recv_window_error(exc: BaseException) -> bool:
        if isinstance(exc, BinanceOrderError):
            return int(exc.code or 0) in (-1021, 1021)
        return False

    def _signed_request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        _time_retries_left: int = 2,
    ) -> dict[str, Any] | list[Any]:
        if not self.api_key or not self.api_secret:
            raise RuntimeError("Missing Binance API credentials")
        try:
            self.sync_server_time(force=False)
        except Exception as exc:
            log.warning("[TIME SYNC] lazy sync failed: %s", exc)
        try:
            return self._signed_request_once(method, path, params)
        except BinanceOrderError as exc:
            if _time_retries_left > 0 and self._is_timestamp_recv_window_error(exc):
                try:
                    from monitoring.logger import log as daily_log

                    daily_log(
                        f"[TIME SYNC] retrying after -1021 | {method} {path} | "
                        f"retries_left={_time_retries_left} | msg={exc.msg}"
                    )
                except Exception:
                    pass
                self.sync_server_time(force=True)
                return self._signed_request(
                    method, path, params, _time_retries_left=_time_retries_left - 1
                )
            raise

    def _signed_request_once(
        self, method: str, path: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | list[Any]:
        payload = {k: str(v) for k, v in (params or {}).items() if v is not None}
        payload["timestamp"] = str(self._request_timestamp_ms())
        payload.setdefault("recvWindow", str(int(self._recv_window_ms)))
        query = urlencode(sorted(payload.items()))
        signature = _sign_query(self.api_secret, query)
        url = f"{self.base_url}{path}?{query}&signature={signature}"
        headers = {"X-MBX-APIKEY": self.api_key}
        request = Request(url=url, method=method.upper(), headers=headers)
        try:
            with urlopen(request, timeout=30) as response:
                status_code = int(response.getcode() or 0)
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8")
            except Exception:
                body = ""
            raise self._to_order_error(
                status_code=int(getattr(exc, "code", 0) or 0),
                body=body,
                request_params=payload,
                fallback_msg=f"HTTPError: {exc.reason}",
            ) from exc
        except URLError as exc:
            raise self._to_order_error(
                status_code=None,
                body=None,
                request_params=payload,
                fallback_msg=f"URLError: {exc.reason}",
            ) from exc
        except Exception as exc:
            if BinanceAPIException is not None and isinstance(exc, BinanceAPIException):
                status_code = int(getattr(exc, "status_code", 0) or 0) or None
                code = getattr(exc, "code", None)
                msg = str(getattr(exc, "message", "") or str(exc))
                raise BinanceOrderError(
                    status_code=status_code,
                    code=int(code) if isinstance(code, int | float | str) and str(code).lstrip("-").isdigit() else None,
                    msg=msg,
                    request_params=dict(payload),
                    raw_response=str(exc),
                ) from exc
            if RequestException is not None and isinstance(exc, RequestException):
                response = getattr(exc, "response", None)
                body = getattr(response, "text", None) if response is not None else None
                status = int(getattr(response, "status_code", 0) or 0) or None
                raise self._to_order_error(
                    status_code=status,
                    body=body,
                    request_params=payload,
                    fallback_msg=f"RequestException: {exc}",
                ) from exc
            raise self._to_order_error(
                status_code=None,
                body=None,
                request_params=payload,
                fallback_msg=f"Unexpected request error: {exc}",
            ) from exc

        data = self._safe_json_decode(body)
        if status_code >= 400:
            raise self._to_order_error(
                status_code=status_code,
                body=body,
                request_params=payload,
                fallback_msg=f"Binance error status {status_code}",
            )
        if isinstance(data, dict | list):
            return data
        return {}

    def get_mark_price(self, symbol: str) -> float:
        """Latest futures mark/last price for min-notional checks."""
        sym_u = symbol.strip().upper()
        url = f"{self.base_url}/fapi/v1/ticker/price?symbol={sym_u}"
        req = Request(url=url, method="GET")
        try:
            with urlopen(req, timeout=15) as response:
                body = response.read().decode("utf-8")
        except Exception as exc:
            raise RuntimeError(f"Failed to fetch mark price for {sym_u}: {exc}") from exc
        parsed = self._safe_json_decode(body)
        if isinstance(parsed, dict):
            try:
                px = float(parsed.get("price", 0.0))
            except (TypeError, ValueError):
                px = 0.0
            if px > 0.0:
                return px
        raise RuntimeError(f"Invalid mark price response for {sym_u}")

    def create_market_order(
        self, symbol: str, side: str, amount: float, *, position_side: str | None = None
    ) -> dict[str, Any]:
        """Create a USDT-M futures MARKET order."""
        sym_u = symbol.strip().upper()
        side_u = side.strip().upper()
        try:
            mark_px = self.get_mark_price(sym_u)
        except Exception:
            mark_px = 0.0
        if mark_px > 0.0:
            rounded_qty = self.normalize_entry_qty(sym_u, float(amount), entry_price=mark_px)
        else:
            rounded_qty = self._normalize_order_qty(sym_u, float(amount))
        if rounded_qty <= 0:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=f"Filter failure: LOT_SIZE (quantity={amount} rounded to 0)",
                request_params={
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "MARKET",
                    "quantity": self._format_qty(amount),
                },
            )
        leg = position_side or position_side_for_entry(side_u)

        def build_payload(
            hedge: bool,
            *,
            position_side_override: str | None = None,
            apply_env_hedge_force: bool = False,
        ) -> dict[str, Any]:
            ps = position_side_override if position_side_override is not None else leg
            use_hedge = bool(hedge)
            if apply_env_hedge_force and self._position_mode_setting == "hedge":
                use_hedge = True
            if use_hedge and not ps:
                ps = position_side_for_entry(side_u)
            return self._apply_position_side(
                {
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "MARKET",
                    "quantity": self._format_qty(rounded_qty),
                },
                ps if use_hedge else None,
                hedge=use_hedge,
            )

        try:
            return self._post_order_with_position_mode_retry(
                "/fapi/v1/order",
                build_payload,
                side_for_leg=side_u,
                position_side=leg,
                apply_env_hedge_force_on_first=self._position_mode_setting == "hedge",
            )
        except BinanceOrderError:
            raise
        except Exception as exc:
            raise self._to_order_error(
                status_code=None,
                body=None,
                request_params=build_payload(self.use_hedge_position_side()),
                fallback_msg=f"Unknown order failure: {exc}",
            ) from exc

    def normalize_qty(self, symbol: str, qty: float) -> float:
        """Round quantity to LOT_SIZE step (public helper for stop sync)."""
        return self._normalize_order_qty(symbol.strip().upper(), float(qty))

    def market_min_notional_usdt(self, symbol: str) -> float:
        """MIN_NOTIONAL filter for MARKET entries (USDT); loads symbol filters if needed."""
        sym = symbol.strip().upper()
        if sym in self._min_notional_cache:
            return float(self._min_notional_cache[sym])
        self._lot_constraints(sym)
        return float(self._min_notional_cache.get(sym, 5.0))

    def normalize_entry_qty(self, symbol: str, qty: float, *, entry_price: float) -> float:
        """Round to MARKET lot step and cap to max qty (no min-notional bump)."""
        _ = entry_price
        sym = symbol.strip().upper()
        cons = self._lot_constraints(sym)
        rounded = self._round_quantity_to_lot_step(float(qty), cons.step)
        if rounded > cons.max_qty:
            rounded = self._round_quantity_to_lot_step(cons.max_qty, cons.step)
        if rounded < cons.min_qty:
            rounded = 0.0
        return rounded

    def _ensure_min_notional_qty(
        self,
        symbol: str,
        qty: float,
        *,
        cons: LotConstraints,
        entry_price: float,
    ) -> float:
        """Bump qty by lot steps until notional >= exchange MIN_NOTIONAL."""
        rounded = float(qty)
        if rounded <= 0.0:
            return 0.0
        min_n = self.market_min_notional_usdt(symbol)
        px = max(float(entry_price), 1e-12)
        if min_n <= 0.0:
            return rounded
        step = max(float(cons.step), 1e-12)
        while rounded * px + 1e-9 < min_n:
            needed = self._round_quantity_to_lot_step_up(min_n / px, step)
            needed = max(needed, rounded + step, cons.min_qty)
            if needed <= rounded:
                needed = rounded + step
            rounded = needed
            if rounded > cons.max_qty:
                return 0.0
        return rounded

    def normalize_stop_price(self, symbol: str, price: float) -> float:
        """Round stop price to PRICE_FILTER tick (public helper for stop sync)."""
        return self._normalize_price_to_tick(symbol.strip().upper(), float(price))

    def price_tick_size(self, symbol: str) -> float:
        return float(self._price_tick_size(symbol.strip().upper()))

    def lot_size_step(self, symbol: str) -> float:
        return float(self._lot_constraints(symbol.strip().upper()).step)

    def market_lot_constraints(self, symbol: str) -> LotConstraints:
        """LOT filters for MARKET orders (uses MARKET_LOT_SIZE when present)."""
        return self._lot_constraints(symbol.strip().upper())

    def market_max_order_qty(self, symbol: str) -> float:
        return float(self.market_lot_constraints(symbol).max_qty)

    def get_futures_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Query a single USDT-M futures order by id (for TP limit fill detection)."""
        sym_u = symbol.strip().upper()
        data = self._signed_request(
            "GET",
            "/fapi/v1/order",
            {"symbol": sym_u, "orderId": str(int(order_id))},
        )
        if not isinstance(data, dict):
            raise RuntimeError(f"Invalid order response for {sym_u} orderId={order_id}")
        return data

    def get_futures_algo_order(self, algo_id: int, *, symbol: str | None = None) -> dict[str, Any]:
        """Query a single conditional algo order by algoId (TP2 / BE STOP after Dec 2025 migration)."""
        params: dict[str, Any] = {"algoId": str(int(algo_id))}
        if symbol and str(symbol).strip():
            params["symbol"] = str(symbol).strip().upper()
        data = self._signed_request("GET", "/fapi/v1/algoOrder", params)
        if not isinstance(data, dict):
            raise RuntimeError(f"Invalid algo order response for algoId={algo_id}")
        return data

    def get_tp2_take_profit_market_algo_order(self, algo_id: int) -> dict[str, Any]:
        """Query TP2 TAKE_PROFIT_MARKET via exact placement endpoint (GET /fapi/v1/algoOrder)."""
        return self.get_futures_algo_order(int(algo_id))

    def get_open_algo_orders(self, symbol: str) -> list[dict[str, Any]]:
        """Open conditional algo orders for one symbol (near real-time on Binance)."""
        sym_u = symbol.strip().upper()
        payload = self._signed_request(
            "GET",
            "/fapi/v1/openAlgoOrders",
            {"symbol": sym_u},
        )
        return payload if isinstance(payload, list) else []

    def cancel_futures_order(self, symbol: str, order_id: int) -> dict[str, Any]:
        """Cancel a single futures order by id (USDT-M)."""
        sym_u = symbol.strip().upper()
        return self._signed_request(
            "DELETE",
            "/fapi/v1/order",
            {"symbol": sym_u, "orderId": str(int(order_id))},
        )

    def create_conditional_stop_market_order(
        self,
        symbol: str,
        side: str,
        stop_price: float,
        *,
        quantity: float | None = None,
        close_position: bool = False,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = True,
    ) -> dict[str, Any]:
        """
        Binance conditional STOP_MARKET via ``/fapi/v1/algoOrder`` (algoType=CONDITIONAL).

        Use ``close_position=True`` for post-TP1 breakeven on the full runner (Binance UI
        "Close Position" conditional). Use ``quantity`` for partial protective stops.
        """
        sym_u = symbol.strip().upper()
        side_u = side.strip().upper()
        normalized_stop = self._normalize_price_to_tick(sym_u, float(stop_price))
        stop_s = self._format_price(normalized_stop)
        if cancel_all_algo_orders:
            self._cancel_all_open_algo_orders_safe(sym_u)
        leg = position_side or position_side_for_reduce_order(side_u)

        rounded_qty = 0.0
        if not close_position:
            if quantity is None or float(quantity) <= 0:
                raise BinanceOrderError(
                    status_code=None,
                    code=-1013,
                    msg="quantity required when close_position is false",
                    request_params={
                        "symbol": sym_u,
                        "side": side_u,
                        "type": "STOP_MARKET",
                        "quantity": str(quantity),
                    },
                )
            rounded_qty = self._normalize_order_qty(sym_u, float(quantity))
            if rounded_qty <= 0:
                raise BinanceOrderError(
                    status_code=None,
                    code=-1013,
                    msg=f"Filter failure: LOT_SIZE (quantity={quantity} rounded to 0)",
                    request_params={
                        "symbol": sym_u,
                        "side": side_u,
                        "type": "STOP_MARKET",
                        "quantity": self._format_qty(quantity),
                    },
                )

        def build_payload(
            hedge: bool,
            *,
            position_side_override: str | None = None,
        ) -> dict[str, Any]:
            ps = position_side_override if position_side_override is not None else leg
            base: dict[str, Any] = {
                "algoType": "CONDITIONAL",
                "symbol": sym_u,
                "side": side_u,
                "type": "STOP_MARKET",
                "triggerPrice": stop_s,
                "workingType": "MARK_PRICE",
            }
            if close_position:
                base["closePosition"] = "true"
                return self._apply_position_side(base, ps if hedge else None, hedge=hedge)
            return self._apply_position_side(
                self._apply_reduce_only(
                    {
                        **base,
                        "quantity": self._format_qty(rounded_qty),
                    },
                    hedge=hedge,
                ),
                ps if hedge else None,
                hedge=hedge,
            )

        data = self._post_order_with_position_mode_retry(
            "/fapi/v1/algoOrder",
            build_payload,
            side_for_leg=side_u,
            position_side=leg,
        )

        if isinstance(data, dict):
            if data.get("orderId") is None and data.get("algoId") is not None:
                data = dict(data)
                data["orderId"] = data.get("algoId")
            return data
        return {}

    def create_conditional_take_profit_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        trigger_price: float,
        *,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = False,
    ) -> dict[str, Any]:
        """Conditional TAKE_PROFIT_MARKET via ``/fapi/v1/algoOrder`` (coexists with BE STOP conditional)."""
        sym_u = symbol.strip().upper()
        side_u = side.strip().upper()
        trigger = self._normalize_price_to_tick(sym_u, float(trigger_price))
        if trigger <= 0.0:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=f"Invalid take-profit trigger ({trigger_price})",
                request_params={
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "TAKE_PROFIT_MARKET",
                    "triggerPrice": trigger_price,
                },
            )
        rounded_qty = self._normalize_order_qty(sym_u, float(quantity))
        if rounded_qty <= 0.0:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=f"Filter failure: LOT_SIZE (quantity={quantity} rounded to 0)",
                request_params={
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "TAKE_PROFIT_MARKET",
                    "quantity": self._format_qty(quantity),
                },
            )
        if cancel_all_algo_orders:
            self._cancel_all_open_algo_orders_safe(sym_u)
        leg = position_side or position_side_for_reduce_order(side_u)
        trigger_s = self._format_price(trigger)

        def build_payload(
            hedge: bool,
            *,
            position_side_override: str | None = None,
        ) -> dict[str, Any]:
            ps = position_side_override if position_side_override is not None else leg
            base: dict[str, Any] = {
                "algoType": "CONDITIONAL",
                "symbol": sym_u,
                "side": side_u,
                "type": "TAKE_PROFIT_MARKET",
                "quantity": self._format_qty(rounded_qty),
                "triggerPrice": trigger_s,
                "workingType": "MARK_PRICE",
            }
            return self._apply_position_side(
                self._apply_reduce_only(base, hedge=hedge),
                ps if hedge else None,
                hedge=hedge,
            )

        data = self._post_order_with_position_mode_retry(
            "/fapi/v1/algoOrder",
            build_payload,
            side_for_leg=side_u,
            position_side=leg,
        )
        if isinstance(data, dict):
            if data.get("orderId") is None and data.get("algoId") is not None:
                data = dict(data)
                data["orderId"] = data.get("algoId")
            return data
        return {}

    def create_reduce_only_stop_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        *,
        position_side: str | None = None,
        cancel_all_algo_orders: bool = True,
    ) -> dict[str, Any]:
        """
        Quantity-based protective STOP_MARKET (reduce-only conditional algo order).

        Binance requires conditional stops via ``/fapi/v1/algoOrder`` (-4120 on ``/fapi/v1/order``).
        Response may use ``algoId``; we copy it to ``orderId`` for existing cancel/replace code.
        """
        return self.create_conditional_stop_market_order(
            symbol,
            side,
            stop_price,
            quantity=float(quantity),
            close_position=False,
            position_side=position_side,
            cancel_all_algo_orders=cancel_all_algo_orders,
        )

    def cancel_futures_stop_order(self, symbol: str, order_or_algo_id: int) -> dict[str, Any]:
        """
        Cancel a protective stop placed either as an algo order (algoId) or legacy order (orderId).
        Tries algo cancel first, then classic cancel.
        """
        sym_u = symbol.strip().upper()
        oid = int(order_or_algo_id)
        last_exc: BinanceOrderError | None = None
        for path, params in (
            ("algo", {"algoId": str(oid)}),
            ("classic", {"symbol": sym_u, "orderId": str(oid)}),
        ):
            try:
                if path == "algo":
                    return self._signed_request("DELETE", "/fapi/v1/algoOrder", params)
                return self._signed_request("DELETE", "/fapi/v1/order", params)
            except BinanceOrderError as exc:
                last_exc = exc
                if exc.code in (-2011, -2013):
                    continue
                raise
        if last_exc is not None:
            raise last_exc
        return {}

    def create_reduce_only_market_order(
        self, symbol: str, side: str, amount: float, *, position_side: str | None = None
    ) -> dict[str, Any]:
        """Close part/all of a futures position via reduce-only MARKET order."""
        sym_u = symbol.strip().upper()
        side_u = side.strip().upper()
        rounded_qty = self._normalize_order_qty(sym_u, float(amount))
        if rounded_qty <= 0:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=f"Filter failure: LOT_SIZE (quantity={amount} rounded to 0)",
                request_params={
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "MARKET",
                    "reduceOnly": "true",
                    "quantity": self._format_qty(amount),
                },
            )
        leg = position_side

        def build_payload(
            hedge: bool,
            *,
            position_side_override: str | None = None,
        ) -> dict[str, Any]:
            ps = position_side_override if position_side_override is not None else leg
            return self._apply_position_side(
                self._apply_reduce_only(
                    {
                        "symbol": sym_u,
                        "side": side_u,
                        "type": "MARKET",
                        "quantity": self._format_qty(rounded_qty),
                    },
                    hedge=hedge,
                ),
                ps if hedge else None,
                hedge=hedge,
            )

        return self._post_order_with_position_mode_retry(
            "/fapi/v1/order",
            build_payload,
            side_for_leg=side_u,
            position_side=leg,
        )

    def create_reduce_only_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        *,
        position_side: str | None = None,
        time_in_force: str = "GTC",
    ) -> dict[str, Any]:
        """Place a reduce-only LIMIT take-profit (regular /fapi/v1/order, not algo)."""
        sym_u = symbol.strip().upper()
        side_u = side.strip().upper()
        px = self._normalize_price_to_tick(sym_u, float(price))
        if px <= 0.0:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=f"Invalid limit price ({price})",
                request_params={"symbol": sym_u, "side": side_u, "type": "LIMIT", "price": price},
            )
        rounded_qty = self._normalize_order_qty(sym_u, float(quantity))
        if rounded_qty <= 0.0:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=f"Filter failure: LOT_SIZE (quantity={quantity} rounded to 0)",
                request_params={
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "LIMIT",
                    "quantity": self._format_qty(quantity),
                    "price": self._format_price(px),
                },
            )
        min_n = self.market_min_notional_usdt(sym_u)
        if rounded_qty * px + 1e-9 < min_n:
            raise BinanceOrderError(
                status_code=None,
                code=-1013,
                msg=(
                    f"Filter failure: MIN_NOTIONAL (qty={rounded_qty} price={px} "
                    f"notional={rounded_qty * px:.4f} < {min_n})"
                ),
                request_params={
                    "symbol": sym_u,
                    "side": side_u,
                    "type": "LIMIT",
                    "quantity": self._format_qty(rounded_qty),
                    "price": self._format_price(px),
                },
            )
        leg = position_side
        tif = str(time_in_force or "GTC").strip().upper()

        def build_payload(
            hedge: bool,
            *,
            position_side_override: str | None = None,
        ) -> dict[str, Any]:
            ps = position_side_override if position_side_override is not None else leg
            return self._apply_position_side(
                self._apply_reduce_only(
                    {
                        "symbol": sym_u,
                        "side": side_u,
                        "type": "LIMIT",
                        "timeInForce": tif,
                        "quantity": self._format_qty(rounded_qty),
                        "price": self._format_price(px),
                    },
                    hedge=hedge,
                ),
                ps if hedge else None,
                hedge=hedge,
            )

        return self._post_order_with_position_mode_retry(
            "/fapi/v1/order",
            build_payload,
            side_for_leg=side_u,
            position_side=leg,
        )

    def get_user_trades(
        self,
        symbol: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return recent futures account trades for one symbol."""
        sym_u = symbol.strip().upper()
        payload = self._signed_request(
            "GET",
            "/fapi/v1/userTrades",
            {
                "symbol": sym_u,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": max(1, min(int(limit), 1000)),
            },
        )
        return payload if isinstance(payload, list) else []

    def get_all_algo_orders(
        self,
        symbol: str,
        *,
        start_time_ms: int | None = None,
        end_time_ms: int | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return historical futures algo orders for one symbol."""
        sym_u = symbol.strip().upper()
        payload = self._signed_request(
            "GET",
            "/fapi/v1/allAlgoOrders",
            {
                "symbol": sym_u,
                "startTime": start_time_ms,
                "endTime": end_time_ms,
                "limit": max(1, min(int(limit), 1000)),
            },
        )
        return payload if isinstance(payload, list) else []

    def cancel_all_open_algo_orders(self, symbol: str) -> dict[str, Any]:
        """
        Cancel all open algorithmic (conditional) orders for a symbol.

        Required before placing a new closePosition STOP when Binance still holds a prior
        GTE closePosition algo (-4130: duplicate in same direction).
        """
        sym_u = symbol.strip().upper()
        return self._signed_request("DELETE", "/fapi/v1/algoOpenOrders", {"symbol": sym_u})

    def _cancel_all_open_algo_orders_safe(self, symbol: str) -> None:
        sym_u = symbol.strip().upper()
        try:
            self.cancel_all_open_algo_orders(sym_u)
        except BinanceOrderError as exc:
            log.warning("cancel_all_open_algo_orders %s: %s (code=%s)", sym_u, exc.msg, exc.code)
        except Exception as exc:
            log.warning("cancel_all_open_algo_orders %s: %s", sym_u, exc)

    def create_stop_market_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
        *,
        position_side: str | None = None,
    ) -> dict[str, Any]:
        """
        Create protective STOP_MARKET order.

        Primary mode uses closePosition=true (Binance-recommended conditional close format).
        Fallback mode uses reduceOnly + quantity for environments that still accept it.
        """
        sym_u = symbol.strip().upper()
        side_u = side.strip().upper()
        normalized_stop = self._normalize_price_to_tick(sym_u, float(stop_price))
        stop_s = self._format_price(normalized_stop)

        hedge = self.use_hedge_position_side()
        # Primary payload: Futures Algo Order API (conditional close-all trigger).
        primary_payload = self._apply_position_side(
            {
                "algoType": "CONDITIONAL",
                "symbol": sym_u,
                "side": side_u,
                "type": "STOP_MARKET",
                "triggerPrice": stop_s,
                "closePosition": "true",
                "workingType": "MARK_PRICE",
            },
            position_side,
            hedge=hedge,
        )
        # Binance allows only one closePosition conditional per symbol/direction; clear stale algos.
        self._cancel_all_open_algo_orders_safe(sym_u)
        algo_exc: BinanceOrderError | None = None
        try:
            return self._signed_request("POST", "/fapi/v1/algoOrder", primary_payload)
        except BinanceOrderError as primary_exc:
            algo_exc = primary_exc
            if primary_exc.code == -4130:
                self._cancel_all_open_algo_orders_safe(sym_u)
                try:
                    return self._signed_request("POST", "/fapi/v1/algoOrder", primary_payload)
                except BinanceOrderError as retry_exc:
                    algo_exc = retry_exc
            rounded_qty = self._normalize_order_qty(sym_u, float(amount))
            if rounded_qty <= 0:
                raise algo_exc
            fallback_payload = self._apply_position_side(
                self._apply_reduce_only(
                    {
                        "symbol": sym_u,
                        "side": side_u,
                        "type": "STOP_MARKET",
                        "stopPrice": stop_s,
                        "quantity": self._format_qty(rounded_qty),
                        "workingType": "MARK_PRICE",
                    },
                    hedge=hedge,
                ),
                position_side,
                hedge=hedge,
            )
            try:
                return self._signed_request("POST", "/fapi/v1/order", fallback_payload)
            except BinanceOrderError:
                raise algo_exc

    def get_balance(self) -> float:
        """Return wallet balance in USDT from futures account."""
        account = self._signed_request("GET", "/fapi/v2/account", {})
        try:
            return float(account.get("totalWalletBalance", 0.0))
        except (TypeError, ValueError):
            log.warning("Could not parse totalWalletBalance from account payload")
            return 0.0

    def get_account_metrics(self) -> dict[str, float]:
        """
        Return account-level futures metrics used for live/demo sizing.
        """
        account = self._signed_request("GET", "/fapi/v2/account", {})
        if not isinstance(account, dict):
            return {
                "total_wallet_balance": 0.0,
                "total_margin_balance": 0.0,
                "available_balance": 0.0,
                "open_notional": 0.0,
            }
        try:
            total_wallet_balance = float(account.get("totalWalletBalance", 0.0))
        except (TypeError, ValueError):
            total_wallet_balance = 0.0
        try:
            total_margin_balance = float(account.get("totalMarginBalance", total_wallet_balance))
        except (TypeError, ValueError):
            total_margin_balance = total_wallet_balance
        try:
            available_balance = float(account.get("availableBalance", 0.0))
        except (TypeError, ValueError):
            available_balance = 0.0
        open_notional = 0.0
        rows = account.get("positions")
        if isinstance(rows, list):
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    open_notional += abs(float(row.get("notional", 0.0)))
                except (TypeError, ValueError):
                    continue
        return {
            "total_wallet_balance": max(0.0, total_wallet_balance),
            "total_margin_balance": max(0.0, total_margin_balance),
            "available_balance": max(0.0, available_balance),
            "open_notional": max(0.0, open_notional),
        }

    def set_symbol_leverage(self, symbol: str, leverage: int) -> dict[str, Any]:
        """Set USDT-M futures leverage for a symbol."""
        sym_u = symbol.strip().upper()
        lev = max(1, int(leverage))
        payload = {
            "symbol": sym_u,
            "leverage": str(lev),
        }
        return self._signed_request("POST", "/fapi/v1/leverage", payload)

    def has_open_position_size(self, symbol: str) -> bool:
        """
        True if the symbol has non-zero size on the exchange.

        Hedge mode: any LONG or SHORT leg (not net sum — opposing legs must not mask each other).
        One-way: single net positionAmt.
        """
        sym_u = symbol.strip().upper()
        if self.use_hedge_position_side():
            for leg in ("LONG", "SHORT"):
                if abs(float(self.get_position_amount(sym_u, leg))) > 1e-10:
                    return True
            return False
        return abs(float(self.get_position_amount(sym_u))) > 1e-10

    def open_position_summary(self, symbol: str) -> str:
        """Short description for skip/block logs (hedge shows per-leg sizes)."""
        sym_u = symbol.strip().upper()
        if self.use_hedge_position_side():
            parts: list[str] = []
            for leg in ("LONG", "SHORT"):
                amt = float(self.get_position_amount(sym_u, leg))
                if abs(amt) > 1e-10:
                    parts.append(f"{leg}={amt:.8f}")
            return ", ".join(parts) if parts else "flat"
        amt = float(self.get_position_amount(sym_u))
        return f"positionAmt={amt:.8f}" if abs(amt) > 1e-10 else "flat"

    def get_position_amount(self, symbol: str, position_side: str | None = None) -> float:
        """Return signed position amount (positive=long, negative=short, zero=flat)."""
        return float(
            self.get_position_risk_snapshot(symbol, position_side=position_side).get("position_amt", 0.0)
        )

    def get_position_risk_snapshot(
        self, symbol: str, position_side: str | None = None
    ) -> dict[str, float]:
        """
        USDT-M positionRisk for one symbol: net positionAmt and size-weighted entryPrice.
        """
        sym_u = symbol.strip().upper()
        leg = str(position_side).strip().upper() if position_side else ""
        payload = self._signed_request("GET", "/fapi/v2/positionRisk", {"symbol": sym_u})
        if not isinstance(payload, list):
            return {"position_amt": 0.0, "entry_price": 0.0}
        net_amt = 0.0
        entry_num = 0.0
        entry_den = 0.0
        for row in payload:
            if not isinstance(row, dict):
                continue
            if str(row.get("symbol", "")).upper() != sym_u:
                continue
            row_leg = str(row.get("positionSide", "BOTH")).upper()
            if leg and row_leg not in ("", "BOTH") and row_leg != leg:
                continue
            try:
                amt = float(row.get("positionAmt", 0.0))
            except (TypeError, ValueError):
                amt = 0.0
            if leg == "LONG" and row_leg == "LONG":
                net_amt = amt
            elif leg == "SHORT" and row_leg == "SHORT":
                net_amt = amt
            else:
                net_amt += amt
            a = abs(amt)
            if a <= 1e-12:
                continue
            try:
                ep = float(row.get("entryPrice", 0.0))
            except (TypeError, ValueError):
                ep = 0.0
            if ep > 0.0:
                entry_num += a * ep
                entry_den += a
        entry = entry_num / entry_den if entry_den > 0.0 else 0.0
        return {"position_amt": net_amt, "entry_price": entry}

    @staticmethod
    def _format_qty(qty: float) -> str:
        s = f"{float(qty):.8f}".rstrip("0").rstrip(".")
        return s if s else "0"

    @staticmethod
    def _format_price(price: float) -> str:
        s = f"{float(price):.12f}".rstrip("0").rstrip(".")
        return s if s else "0"

    def _normalize_order_qty(self, symbol: str, qty: float) -> float:
        cons = self._lot_constraints(symbol)
        rounded = self._round_quantity_to_lot_step(qty, cons.step)
        if rounded > cons.max_qty:
            rounded = self._round_quantity_to_lot_step(cons.max_qty, cons.step)
        if rounded < cons.min_qty:
            return 0.0
        return rounded

    def _normalize_price_to_tick(self, symbol: str, price: float) -> float:
        tick = self._price_tick_size(symbol)
        if tick <= 0:
            return float(price)
        n = math.floor(float(price) / float(tick) + 1e-12)
        return round(n * tick, 12)

    def _lot_constraints(self, symbol: str) -> LotConstraints:
        sym = symbol.strip().upper()
        cached = self._lot_size_cache.get(sym)
        if cached is not None:
            return cached
        url = f"{self.base_url}/fapi/v1/exchangeInfo?symbol={sym}"
        req = Request(url=url, method="GET")
        try:
            with urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
        except Exception:
            fallback = LotConstraints(step=0.001, min_qty=0.001, max_qty=1e9)
            self._lot_size_cache[sym] = fallback
            self._min_notional_cache[sym] = 5.0
            return fallback
        parsed = self._safe_json_decode(body)
        if isinstance(parsed, dict):
            for sym_row in parsed.get("symbols", []):
                if str(sym_row.get("symbol", "")).upper() != sym:
                    continue
                lot: LotConstraints | None = None
                market: LotConstraints | None = None
                min_notional = 5.0
                for filt in sym_row.get("filters", []):
                    if not isinstance(filt, dict):
                        continue
                    ft = str(filt.get("filterType", "")).upper()
                    if ft == "MIN_NOTIONAL":
                        try:
                            min_notional = max(0.0, float(filt.get("notional", min_notional)))
                        except (TypeError, ValueError):
                            pass
                        continue
                    if ft == "NOTIONAL":
                        try:
                            min_notional = max(
                                min_notional,
                                float(filt.get("minNotional", filt.get("notional", min_notional))),
                            )
                        except (TypeError, ValueError):
                            pass
                        continue
                    try:
                        step = float(filt.get("stepSize", 0.001))
                        min_qty = float(filt.get("minQty", 0.001))
                        max_qty = float(filt.get("maxQty", 1e9))
                    except (TypeError, ValueError):
                        continue
                    cons = LotConstraints(
                        step=max(step, 1e-12),
                        min_qty=max(min_qty, 0.0),
                        max_qty=max(max_qty, 0.0),
                    )
                    if ft == "LOT_SIZE":
                        lot = cons
                    elif ft == "MARKET_LOT_SIZE":
                        market = cons
                self._min_notional_cache[sym] = min_notional
                if market is not None:
                    self._lot_size_cache[sym] = market
                    return market
                if lot is not None:
                    self._lot_size_cache[sym] = lot
                    return lot
        fallback = LotConstraints(step=0.001, min_qty=0.001, max_qty=1e9)
        self._lot_size_cache[sym] = fallback
        self._min_notional_cache[sym] = 5.0
        return fallback

    def _lot_size_constraints(self, symbol: str) -> tuple[float, float, float]:
        """Backward-compatible (step, min_qty, max_qty) for market orders."""
        cons = self._lot_constraints(symbol)
        return cons.step, cons.min_qty, cons.max_qty

    def _price_tick_size(self, symbol: str) -> float:
        sym = symbol.strip().upper()
        cached = self._price_tick_cache.get(sym)
        if cached is not None:
            return cached
        url = f"{self.base_url}/fapi/v1/exchangeInfo?symbol={sym}"
        req = Request(url=url, method="GET")
        try:
            with urlopen(req, timeout=30) as response:
                body = response.read().decode("utf-8")
        except Exception:
            fallback = 0.01
            self._price_tick_cache[sym] = fallback
            return fallback
        parsed = self._safe_json_decode(body)
        if isinstance(parsed, dict):
            for sym_row in parsed.get("symbols", []):
                if str(sym_row.get("symbol", "")).upper() != sym:
                    continue
                for filt in sym_row.get("filters", []):
                    if str(filt.get("filterType", "")).upper() == "PRICE_FILTER":
                        try:
                            tick = float(filt.get("tickSize", 0.01))
                            out = max(tick, 1e-12)
                            self._price_tick_cache[sym] = out
                            return out
                        except (TypeError, ValueError):
                            break
        fallback = 0.01
        self._price_tick_cache[sym] = fallback
        return fallback

    @staticmethod
    def _round_quantity_to_lot_step(quantity: float, step: float) -> float:
        if step <= 0:
            return round(float(quantity), 8)
        n = math.floor(float(quantity) / float(step) + 1e-12)
        return round(n * step, 12)

    @staticmethod
    def _round_quantity_to_lot_step_up(quantity: float, step: float) -> float:
        if step <= 0:
            return round(float(quantity), 8)
        n = math.ceil(float(quantity) / float(step) - 1e-12)
        return round(n * step, 12)

    @staticmethod
    def _safe_json_decode(body: str | None) -> dict[str, Any] | list[Any] | None:
        if not body:
            return None
        try:
            return json.loads(body)
        except Exception:
            return None

    def _to_order_error(
        self,
        *,
        status_code: int | None,
        body: str | None,
        request_params: dict[str, Any],
        fallback_msg: str,
    ) -> BinanceOrderError:
        parsed = self._safe_json_decode(body)
        code: int | None = None
        msg: str = fallback_msg
        if isinstance(parsed, dict):
            raw_code = parsed.get("code")
            raw_msg = parsed.get("msg")
            try:
                code = int(raw_code) if raw_code is not None else None
            except (TypeError, ValueError):
                code = None
            if raw_msg:
                msg = str(raw_msg)
            elif body:
                msg = body
        elif body:
            msg = body
        return BinanceOrderError(
            status_code=status_code,
            code=code,
            msg=msg,
            request_params=dict(request_params),
            raw_response=body,
        )
