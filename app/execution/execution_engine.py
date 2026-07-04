from __future__ import annotations

import logging
import os
import time
from abc import ABC, abstractmethod
from typing import Any

from config import settings
from execution.exchange_client import BinanceExchangeClient, BinanceOrderError
from execution.exchange_order_gateway import ExchangeOrderGateway
from execution.order_service import OrderService
from execution.exchange_tp_orders import (
    exchange_tp_orders_enabled,
    place_tp_limit_orders_after_entry,
)
from execution.position_mode import (
    describe_position_mode,
    position_side_for_entry,
    position_side_for_reduce_order,
)
from execution.risk_manager import RiskConfig
from monitoring.logger import log as daily_log

log = logging.getLogger(__name__)


def _leverage_symbol_label(symbol: str) -> str:
    sym_u = str(symbol).strip().upper()
    if sym_u.endswith("USDT"):
        return sym_u[:-4]
    return sym_u


def _log_leverage_set_summary(symbols: list[str], leverage: int) -> None:
    labels = ", ".join(_leverage_symbol_label(s) for s in symbols)
    msg = f"[LEVERAGE SET] | Symbol={labels} | Leverage={int(leverage)}x | Status=OK"
    print(msg, flush=True)
    daily_log(msg)


def _position_wait_timeout_sec() -> float:
    v = float(getattr(settings, "POSITION_WAIT_AFTER_ENTRY_SEC", 0.0))
    if v > 0.0:
        return min(120.0, v)
    return 15.0


def _fmt_order_error_log(
    *,
    symbol: str,
    side: str,
    qty: float,
    price: float | None,
    order_type: str,
    code: int | None,
    msg: str,
    mode: str | None = None,
    request_symbol: str | None = None,
    request_side: str | None = None,
    request_qty: str | None = None,
    position_amt: float | None = None,
    extra: str | None = None,
) -> str:
    code_part = f"code={code}" if code is not None else "code=unknown"
    price_part = f" price={price}" if price is not None else " price=n/a"
    mode_part = f" mode={mode}" if mode else ""
    req_sym = request_symbol or symbol
    req_side = request_side or side
    req_qty = request_qty or f"{qty:.8f}"
    req_part = f" req[symbol={req_sym} side={req_side} qty={req_qty}]"
    pos_part = (
        f" positionAmt={position_amt:.8f}"
        if position_amt is not None
        else " positionAmt=n/a"
    )
    extra_part = f" | details={extra}" if extra else ""
    return (
        f"[ORDER ERROR]{mode_part} {symbol} {side} qty={qty}{price_part} type={order_type}"
        f" | {code_part} | msg={msg} |{req_part}{pos_part}{extra_part}"
    )


def _load_demo_testnet_credentials() -> tuple[str, str]:
    api_key = os.getenv("BINANCE_TESTNET_API_KEY", "").strip()
    api_secret = (
        os.getenv("BINANCE_TESTNET_SECRET_KEY", "").strip()
        or os.getenv("BINANCE_TESTNET_SECRET", "").strip()
    )
    if not api_key or not api_secret:
        raise RuntimeError(
            "Demo mode requires Binance TESTNET API keys (BINANCE_TESTNET_API_KEY and "
            "BINANCE_TESTNET_SECRET_KEY or BINANCE_TESTNET_SECRET). "
            "No fallback to live API keys is allowed."
        )
    return api_key, api_secret


def ensure_demo_testnet_credentials() -> None:
    _load_demo_testnet_credentials()


class ExecutionEngine(ABC):
    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        sl: float,
        tp: float,
        *,
        risk_percent: float,
        tp2: float | None = None,
        tp1_close_frac: float = 0.5,
        tp2_close_frac: float = 0.3,
    ) -> dict[str, Any] | None:
        raise NotImplementedError

    @abstractmethod
    def close_order(self, symbol: str, side: str, size: float) -> dict[str, Any] | None:
        raise NotImplementedError

    def sync_stop_loss(self, pos: Any) -> bool:
        """Live/demo: align exchange STOP with ManagedPosition; default no-op."""
        return True

    def cancel_orders_for_flat_position(self, pos: Any, *, reason: str = "position_flat") -> bool:
        """Live/demo: cancel SL/TP orders when position is flat; default no-op."""
        _ = (pos, reason)
        return True

    def place_exchange_tp1_after_open(
        self,
        *,
        symbol: str,
        entry_side: str,
        total_qty: float,
        tp1: float,
        tp2: float,
        tp1_close_frac: float,
        tp2_close_frac: float,
    ) -> dict[str, Any] | None:
        """Live/demo: place exchange TP1 limit after entry OPEN is logged. Default no-op."""
        _ = (symbol, entry_side, total_qty, tp1, tp2, tp1_close_frac, tp2_close_frac)
        return None


def _normalize_side(side: str) -> str:
    u = side.strip().upper()
    if u in ("LONG", "BUY"):
        return "BUY"
    if u in ("SHORT", "SELL"):
        return "SELL"
    return u


class BacktestExecutionEngine(ExecutionEngine):
    def __init__(self) -> None:
        self.last_place_order_failure: str | None = None
        target_leverage = int(settings.LEVERAGE)
        symbols = [s.strip().upper() for s in settings.SYMBOLS]
        _log_leverage_set_summary(symbols, target_leverage)

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        sl: float,
        tp: float,
        *,
        risk_percent: float,
        tp2: float | None = None,
        tp1_close_frac: float = 0.5,
        tp2_close_frac: float = 0.3,
    ) -> dict[str, Any] | None:
        _ = (risk_percent, tp2, tp1_close_frac, tp2_close_frac)
        self.last_place_order_failure = None
        return {
            "simulated": True,
            "symbol": symbol.strip().upper(),
            "side": _normalize_side(side),
            "quantity": size,
            "stop_loss": sl,
            "take_profit": tp,
        }

    def close_order(self, symbol: str, side: str, size: float) -> dict[str, Any] | None:
        self.last_place_order_failure = None
        return {
            "simulated": True,
            "symbol": symbol.strip().upper(),
            "side": _normalize_side(side),
            "quantity": float(size),
            "reduceOnly": True,
        }


class _RealExecutionEngine(ExecutionEngine):
    def __init__(self, *, base_url: str, api_key: str, api_secret: str) -> None:
        self._client = BinanceExchangeClient(base_url=base_url, api_key=api_key, api_secret=api_secret)
        self._order_executor = ExchangeOrderGateway(self._client)
        self._executor = OrderService(
            self._order_executor,
            risk_config=RiskConfig(
                max_risk_per_trade=float(settings.MAX_EXECUTION_RISK_PER_TRADE),
                min_confidence=0.0,
                min_entry_position_qty=0.0,
            ),
        )
        self.last_place_order_failure: str | None = None
        self._log_position_mode_startup()
        self._ensure_startup_leverage()

    def _log_position_mode_startup(self) -> None:
        try:
            exchange_dual = self._client.exchange_dual_side_enabled()
            will_send_leg = self._client.use_hedge_position_side()
            daily_log(
                f"[POSITION MODE] {describe_position_mode(self._client.position_mode_label(), hedge_active=exchange_dual)} | "
                f"orders_use_positionSide={will_send_leg}"
            )
            env_mode = self._client.position_mode_label()
            if env_mode == "hedge" and not exchange_dual:
                daily_log(
                    "[POSITION MODE WARN] BINANCE_POSITION_MODE=hedge but exchange is one-way; "
                    "use oneway/auto or enable Hedge Mode in Binance Futures settings."
                )
            elif env_mode == "oneway" and exchange_dual:
                daily_log(
                    "[POSITION MODE WARN] BINANCE_POSITION_MODE=oneway but exchange is hedge; "
                    "use hedge/auto or disable Hedge Mode in Binance Futures settings."
                )
        except Exception as exc:
            daily_log(f"[POSITION MODE WARN] startup check failed | {exc}")

    def _ensure_startup_leverage(self) -> None:
        target_leverage = int(settings.LEVERAGE)
        symbols = [s.strip().upper() for s in settings.SYMBOLS]
        for sym_u in symbols:
            try:
                self._client.set_symbol_leverage(sym_u, target_leverage)
            except BinanceOrderError as exc:
                raise RuntimeError(
                    f"Failed setting startup leverage for {sym_u} to {target_leverage}x: {exc.msg}"
                ) from exc
            except Exception as exc:
                raise RuntimeError(
                    f"Failed setting startup leverage for {sym_u} to {target_leverage}x: {exc}"
                ) from exc
        _log_leverage_set_summary(symbols, target_leverage)

    def _wait_for_position_after_entry(
        self,
        sym_u: str,
        entry_side: str,
        *,
        timeout_sec: float | None = None,
        interval_sec: float = 0.25,
    ) -> bool:
        """
        Polls GET /fapi/v2/positionRisk (via get_position_amount); size can lag the MARKET fill.

        A log line here is NOT a failed SL if you later see stop_loss_order / [OK] in the CLI.
        """
        sd = _normalize_side(entry_side)
        leg = position_side_for_entry(sd) if self._client.use_hedge_position_side() else None
        if timeout_sec is None:
            timeout_sec = _position_wait_timeout_sec()
        deadline = time.monotonic() + float(timeout_sec)
        last_exc: Exception | None = None
        last_amt: float | None = None
        while time.monotonic() < deadline:
            try:
                amt = float(self._client.get_position_amount(sym_u, leg))
                last_amt = amt
                if sd == "BUY" and amt > 1e-10:
                    return True
                if sd == "SELL" and amt < -1e-10:
                    return True
            except Exception as exc:
                last_exc = exc
            time.sleep(interval_sec)
        parts = [
            f"[SYNC] {sym_u} | Exchange shows no open size after {timeout_sec:.0f}s "
            f"(expected {'LONG' if sd == 'BUY' else 'SHORT'}) - submitting reduce-only SL next"
        ]
        if last_amt is not None:
            parts.append(f"last_positionAmt={last_amt:.8f}")
        if last_exc is not None:
            parts.append(f"last_poll_error={type(last_exc).__name__}: {last_exc}")
        daily_log(" | ".join(parts))
        return False

    def place_order(
        self,
        symbol: str,
        side: str,
        size: float,
        sl: float,
        tp: float,
        *,
        risk_percent: float,
        tp2: float | None = None,
        tp1_close_frac: float = 0.5,
        tp2_close_frac: float = 0.3,
    ) -> dict[str, Any] | None:
        self.last_place_order_failure = None
        sym_u = symbol.strip().upper()
        sd = _normalize_side(side)
        qty = float(size)
        tp2_px = float(tp2) if tp2 is not None else float(tp)
        default_error_line = _fmt_order_error_log(
            symbol=sym_u,
            side=sd,
            qty=qty,
            price=None,
            order_type="MARKET",
            code=None,
            msg="unknown order failure",
        )
        try:
            result = self._executor.execute(
                {
                    "symbol": sym_u,
                    "action": sd,
                    "confidence": 1.0,
                    "amount": qty,
                    "risk_percent": float(risk_percent),
                    "balance": 1.0,
                }
            )
        except BinanceOrderError as exc:
            self.last_place_order_failure = str(exc.msg)
            price_raw = exc.request_params.get("price")
            price: float | None = None
            try:
                if price_raw is not None:
                    price = float(price_raw)
            except (TypeError, ValueError):
                price = None
            order_type = str(exc.request_params.get("type", "MARKET")).upper()
            ps = str(exc.request_params.get("positionSide", "") or "").strip().upper()
            ps_part = f" positionSide={ps}" if ps else " positionSide=omitted"
            cfg_mode = getattr(self._client, "position_mode_label", lambda: "?")()
            use_leg = bool(self._client.use_hedge_position_side())
            error_line = _fmt_order_error_log(
                symbol=str(exc.request_params.get("symbol", sym_u)),
                side=str(exc.request_params.get("side", sd)).upper(),
                qty=qty,
                price=price,
                order_type=order_type,
                code=exc.code,
                msg=str(exc.msg),
                mode=settings.MODE,
                request_symbol=str(exc.request_params.get("symbol", sym_u)),
                request_side=str(exc.request_params.get("side", sd)).upper(),
                request_qty=str(exc.request_params.get("quantity", qty)),
                extra=(
                    f"raw_response={exc.raw_response!r}{ps_part} | "
                    f"BINANCE_POSITION_MODE={cfg_mode} | use_hedge_positionSide={use_leg}"
                ),
            )
            daily_log(error_line)
            return None
        except Exception as exc:
            msg = str(exc)
            self.last_place_order_failure = msg
            cfg_mode = getattr(self._client, "position_mode_label", lambda: "?")()
            daily_log(
                _fmt_order_error_log(
                    symbol=sym_u,
                    side=sd,
                    qty=qty,
                    price=None,
                    order_type="MARKET",
                    code=None,
                    msg=msg,
                    mode=settings.MODE,
                    extra=(
                        f"exception_type={type(exc).__name__} | "
                        f"BINANCE_POSITION_MODE={cfg_mode}"
                    ),
                )
            )
            return None
        if not bool(result.get("executed")):
            msg = str(result.get("reason") or "executed=false")
            self.last_place_order_failure = msg
            daily_log(default_error_line.replace("unknown order failure", msg))
            return None
        entry_order = dict(result.get("order") or {})
        if float(sl) <= 0:
            return entry_order
        protective_side = "SELL" if sd == "BUY" else "BUY"
        stop_leg = (
            position_side_for_reduce_order(protective_side)
            if self._client.use_hedge_position_side()
            else None
        )

        position_seen = self._wait_for_position_after_entry(sym_u, sd)
        stop_attempts = (
            int(getattr(settings, "POSITION_STOP_PLACE_ATTEMPTS", 12))
            if not position_seen
            else 1
        )
        stop_sleep = float(getattr(settings, "POSITION_STOP_PLACE_RETRY_SLEEP_SEC", 0.5))

        def _rollback_close(cause_msg: str) -> None:
            try:
                self._order_executor.create_reduce_only_market_order(
                    sym_u, protective_side, qty, position_side=stop_leg
                )
                daily_log(
                    f"[RISK] {sym_u} | entry rolled back via reduce-only MARKET after stop-order failure | "
                    f"reason={cause_msg}"
                )
            except Exception as rollback_exc:
                daily_log(
                    f"[RISK CRITICAL] {sym_u} | stop-order failed and rollback close failed | "
                    f"reason={cause_msg} | rollback_error={rollback_exc}"
                )

        try:
            stop_order = None
            last_stop_exc: BinanceOrderError | Exception | None = None
            used_attempt = 0
            for attempt in range(max(1, stop_attempts)):
                used_attempt = attempt + 1
                try:
                    stop_order = self._order_executor.create_reduce_only_stop_market_order(
                        sym_u,
                        protective_side,
                        qty,
                        float(sl),
                        position_side=stop_leg,
                    )
                    break
                except BinanceOrderError as exc:
                    last_stop_exc = exc
                    if attempt + 1 >= stop_attempts:
                        raise
                    daily_log(
                        f"[SYNC] {sym_u} | SL attempt {attempt + 1}/{stop_attempts} failed "
                        f"(code={exc.code}) | {exc.msg} | retry in {stop_sleep:.1f}s"
                    )
                    time.sleep(stop_sleep)
                except Exception as exc:
                    last_stop_exc = exc
                    if attempt + 1 >= stop_attempts:
                        raise
                    daily_log(
                        f"[SYNC] {sym_u} | SL attempt {attempt + 1}/{stop_attempts} failed "
                        f"| {type(exc).__name__}: {exc} | retry in {stop_sleep:.1f}s"
                    )
                    time.sleep(stop_sleep)
            if stop_order is None:
                raise RuntimeError(
                    f"{sym_u} | SL missing after {stop_attempts} attempts (last_error={last_stop_exc!r})"
                )
            if not position_seen:
                oid_dbg = stop_order.get("orderId") or stop_order.get("algoId")
                daily_log(
                    f"[SYNC] {sym_u} | Reduce-only SL accepted - Position size from API was slow to show | "
                    f"orderId={oid_dbg} | attempts={used_attempt}"
                )
            entry_order["stop_loss_order"] = stop_order
            oid = stop_order.get("orderId")
            if oid is not None:
                try:
                    entry_order["stop_exchange_order_id"] = int(oid)
                except (TypeError, ValueError):
                    entry_order["stop_exchange_order_id"] = None
        except BinanceOrderError as exc:
            cause = f"entry filled but stop-order failed: {exc.msg}"
            self.last_place_order_failure = cause
            stop_price_raw = exc.request_params.get("stopPrice")
            stop_price: float | None = None
            try:
                if stop_price_raw is not None:
                    stop_price = float(stop_price_raw)
            except (TypeError, ValueError):
                stop_price = None
            daily_log(
                _fmt_order_error_log(
                    symbol=str(exc.request_params.get("symbol", sym_u)),
                    side=str(exc.request_params.get("side", protective_side)).upper(),
                    qty=qty,
                    price=stop_price,
                    order_type="STOP_MARKET",
                    code=exc.code,
                    msg=cause,
                    mode=settings.MODE,
                    request_symbol=str(exc.request_params.get("symbol", sym_u)),
                    request_side=str(exc.request_params.get("side", protective_side)).upper(),
                    request_qty=str(exc.request_params.get("quantity", qty)),
                    extra=f"raw_response={exc.raw_response!r}",
                )
            )
            _rollback_close(cause)
            return None
        except Exception as exc:
            msg = str(exc)
            cause = f"entry filled but stop-order failed: {msg}"
            self.last_place_order_failure = cause
            daily_log(
                _fmt_order_error_log(
                    symbol=sym_u,
                    side=protective_side,
                    qty=qty,
                    price=float(sl),
                    order_type="STOP_MARKET",
                    code=None,
                    msg=cause,
                    mode=settings.MODE,
                    extra=f"exception_type={type(exc).__name__}",
                )
            )
            _rollback_close(cause)
            return None

        return entry_order

    def place_exchange_tp1_after_open(
        self,
        *,
        symbol: str,
        entry_side: str,
        total_qty: float,
        tp1: float,
        tp2: float,
        tp1_close_frac: float,
        tp2_close_frac: float,
    ) -> dict[str, Any] | None:
        if not exchange_tp_orders_enabled() or float(tp1) <= 0.0:
            return None
        sym_u = symbol.strip().upper()
        sd = _normalize_side(entry_side)
        try:
            return place_tp_limit_orders_after_entry(
                self._client,
                symbol=sym_u,
                entry_side=sd,
                total_qty=float(total_qty),
                tp1=float(tp1),
                tp2=float(tp2),
                tp1_close_frac=float(tp1_close_frac),
                tp2_close_frac=float(tp2_close_frac),
            )
        except Exception as exc:
            daily_log(f"[TP1 ORDER WARN] {sym_u} | failed to place TP1 limit | {exc}")
            return None

    def sync_stop_loss(self, pos: Any) -> bool:
        from position_management.stop_exchange_sync import update_stop_on_exchange

        return update_stop_on_exchange(pos, self._client)

    def cancel_orders_for_flat_position(self, pos: Any, *, reason: str = "position_flat") -> bool:
        from execution.cancel_position_orders import cancel_orders_for_flat_position_if_live

        result = cancel_orders_for_flat_position_if_live(
            self._client, pos, reason=str(reason)
        )
        return result is not None and not result.errors

    def close_order(self, symbol: str, side: str, size: float) -> dict[str, Any] | None:
        self.last_place_order_failure = None
        sym_u = symbol.strip().upper()
        sd = _normalize_side(side)
        qty = float(size)
        pos_amt: float | None = None
        reduce_leg = position_side_for_reduce_order(sd) if self._client.use_hedge_position_side() else None
        try:
            pos_amt = float(self._client.get_position_amount(sym_u, reduce_leg))
            cannot_reduce = (
                abs(pos_amt) <= 1e-12
                or (sd == "SELL" and pos_amt <= 0.0)
                or (sd == "BUY" and pos_amt >= 0.0)
            )
            if cannot_reduce:
                daily_log(
                    f"[SYNC] {sym_u} | skip reduce-only {sd} qty={qty:.6f} | "
                    f"no reducible position (positionAmt={pos_amt:.8f})"
                )
                return {
                    "skipped": True,
                    "reason": "no_reducible_position",
                    "positionAmt": pos_amt,
                    "symbol": sym_u,
                    "side": sd,
                    "quantity": qty,
                    "reduceOnly": True,
                }
        except Exception as exc:
            daily_log(
                f"[SYNC WARN] {sym_u} | position pre-check failed, sending close anyway | "
                f"reason={exc} | exception_type={type(exc).__name__}"
            )
        try:
            return self._order_executor.create_reduce_only_market_order(
                sym_u, sd, qty, position_side=reduce_leg
            )
        except BinanceOrderError as exc:
            self.last_place_order_failure = str(exc.msg)
            daily_log(
                _fmt_order_error_log(
                    symbol=sym_u,
                    side=sd,
                    qty=qty,
                    price=None,
                    order_type="MARKET_REDUCE_ONLY",
                    code=exc.code,
                    msg=str(exc.msg),
                    mode=settings.MODE,
                    request_symbol=str(exc.request_params.get("symbol", sym_u)),
                    request_side=str(exc.request_params.get("side", sd)).upper(),
                    request_qty=str(exc.request_params.get("quantity", qty)),
                    position_amt=pos_amt,
                    extra=f"raw_response={exc.raw_response!r}",
                )
            )
            return None
        except Exception as exc:
            msg = str(exc)
            self.last_place_order_failure = msg
            daily_log(
                _fmt_order_error_log(
                    symbol=sym_u,
                    side=sd,
                    qty=qty,
                    price=None,
                    order_type="MARKET_REDUCE_ONLY",
                    code=None,
                    msg=msg,
                    mode=settings.MODE,
                    position_amt=pos_amt,
                    extra=f"exception_type={type(exc).__name__}",
                )
            )
            return None


class DemoExecutionEngine(_RealExecutionEngine):
    def __init__(self) -> None:
        key, secret = _load_demo_testnet_credentials()
        super().__init__(base_url=settings.BINANCE_FAPI_REST_BASE, api_key=key, api_secret=secret)


class LiveExecutionEngine(_RealExecutionEngine):
    def __init__(self) -> None:
        super().__init__(
            base_url=settings.BINANCE_FAPI_LIVE_HOST,
            api_key=settings.BINANCE_API_KEY,
            api_secret=settings.BINANCE_SECRET,
        )


def create_execution_engine(mode: str | None = None) -> ExecutionEngine:
    m = (mode or settings.MODE).strip().lower()
    if m == "backtest":
        return BacktestExecutionEngine()
    if m == "demo":
        ensure_demo_testnet_credentials()
        return DemoExecutionEngine()
    if m == "live":
        return LiveExecutionEngine()
    raise ValueError(f"Invalid MODE: {m!r}; expected backtest | demo | live")
