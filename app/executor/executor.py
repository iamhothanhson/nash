from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from analysis.collect_position_metrics import (
    build_entry_snapshot,
    save_entry_snapshot,
)
from app.core.logger import log
from config import settings
from exchange.client import BinanceFuturesClient
from exchange.exceptions import BinanceOrderError
from exchange.utils import position_side_for_direction
from order_planner.models import OrderPlan
from position.archive import save_runtime_position


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    symbol: str
    direction: str
    entry_side: str
    exit_side: str
    position_side: str | None
    qty: float


@dataclass(frozen=True, slots=True)
class EntryFill:
    order_id: int | str | None
    price: float
    qty: float


@dataclass(frozen=True, slots=True)
class ProtectiveOrders:
    stop_loss_order_id: int | str | None
    tp1_order_id: int | str | None


class Executor:
    """Places entry and protective orders on Binance Futures."""

    _client: BinanceFuturesClient | None = None
    _allowed_modes = {"live", "demo"}

    @classmethod
    def _get_client(cls) -> BinanceFuturesClient:
        if cls._client is None:
            cls._client = BinanceFuturesClient()

        return cls._client

    @classmethod
    def execute(cls, plan: OrderPlan) -> dict[str, Any]:
        if settings.MODE not in cls._allowed_modes:
            log(
                f"[EXECUTOR] {plan.symbol} | "
                f"skip (mode={settings.MODE})"
            )
            return {
                "status": "skipped",
                "mode": settings.MODE,
            }

        client = cls._get_client()
        context = cls._build_context(client, plan)

        rejection = cls._check_available_balance(
            client=client,
            plan=plan,
            symbol=context.symbol,
        )
        if rejection is not None:
            return rejection

        entry = cls._place_entry_order(
            client=client,
            plan=plan,
            context=context,
        )

        protective_orders = cls._place_protective_orders(
            client=client,
            plan=plan,
            context=context,
            filled_qty=entry.qty,
        )

        cls._save_entry_snapshot(
            plan=plan,
            symbol=context.symbol,
            direction=context.direction,
        )

        position_data = cls._build_position_data(
            client=client,
            plan=plan,
            context=context,
            entry=entry,
            protective_orders=protective_orders,
        )
        save_runtime_position(position_data)

        log(
            f"[EXECUTOR] {context.symbol} | "
            "Position saved to runtime/positions.json"
        )

        result = {
            "status": "placed",
            "symbol": context.symbol,
            "direction": context.direction,
            "entry_order_id": entry.order_id,
            "entry_price": entry.price,
            "filled_qty": entry.qty,
        }

        log(f"[EXECUTOR] {context.symbol} | Done — {result}")
        return result

    @classmethod
    def _build_context(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
    ) -> ExecutionContext:
        symbol = plan.symbol.strip().upper()
        direction = plan.direction.strip().upper()

        if direction not in {"LONG", "SHORT"}:
            raise BinanceOrderError(
                -1,
                f"Invalid direction: {plan.direction}",
            )

        hedge_mode = settings.BINANCE_POSITION_MODE == "hedge"

        entry_side = "BUY" if direction == "LONG" else "SELL"
        exit_side = "SELL" if entry_side == "BUY" else "BUY"

        position_side = position_side_for_direction(
            direction,
            hedge_mode=hedge_mode,
        )

        qty = client.normalize_qty(symbol, plan.qty)

        if qty <= 0:
            raise BinanceOrderError(
                -1,
                f"Invalid quantity {plan.qty} after normalization",
            )

        return ExecutionContext(
            symbol=symbol,
            direction=direction,
            entry_side=entry_side,
            exit_side=exit_side,
            position_side=position_side,
            qty=qty,
        )

    @classmethod
    def _check_available_balance(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
        symbol: str,
    ) -> dict[str, Any] | None:
        account = client.get_account()

        available_balance = float(
            account.get("availableBalance") or 0
        )
        leverage = cls._get_leverage()
        required_margin = float(plan.notional) / leverage

        if available_balance >= required_margin:
            return None

        reason = (
            "Insufficient available balance: "
            f"have {available_balance:.2f} USDT, "
            f"need approximately {required_margin:.2f} USDT margin "
            f"for a {plan.notional:.2f} USDT position"
        )

        log(f"[EXECUTOR] {symbol} | {reason}")

        return {
            "status": "rejected",
            "reason": reason,
            "available_balance": available_balance,
            "required_margin": required_margin,
        }

    @classmethod
    def _place_entry_order(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
        context: ExecutionContext,
    ) -> EntryFill:
        payload: dict[str, Any] = {
            "symbol": context.symbol,
            "side": context.entry_side,
            "type": "MARKET",
            "quantity": context.qty,
            "newOrderRespType": "RESULT",
        }

        cls._add_position_side(
            payload,
            context.position_side,
        )

        log(
            f"[EXECUTOR] {context.symbol} | "
            f"ENTER {context.entry_side} qty={context.qty}"
        )

        response = client.place_order(payload)

        fill = EntryFill(
            order_id=response.get("orderId"),
            price=cls._resolve_fill_price(
                response=response,
                fallback_price=plan.entry,
            ),
            qty=cls._resolve_filled_qty(
                response=response,
                fallback_qty=context.qty,
            ),
        )

        log(
            f"[EXECUTOR] {context.symbol} | "
            f"FILLED orderId={fill.order_id} "
            f"price={fill.price} qty={fill.qty}"
        )

        return fill

    @classmethod
    def _place_protective_orders(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
        context: ExecutionContext,
        filled_qty: float,
    ) -> ProtectiveOrders:
        stop_loss_order_id = cls._place_stop_loss(
            client=client,
            plan=plan,
            context=context,
        )

        try:
            tp1_order_id = cls._place_tp1(
                client=client,
                plan=plan,
                context=context,
                filled_qty=filled_qty,
            )
        except Exception:
            log(
                f"[EXECUTOR] {context.symbol} | "
                "TP1 placement failed; stop-loss remains active"
            )
            raise

        return ProtectiveOrders(
            stop_loss_order_id=stop_loss_order_id,
            tp1_order_id=tp1_order_id,
        )

    @classmethod
    def _place_stop_loss(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
        context: ExecutionContext,
    ) -> int | str | None:
        stop_price = client.normalize_price(
            context.symbol,
            plan.stop_loss,
        )

        payload: dict[str, Any] = {
            "symbol": context.symbol,
            "side": context.exit_side,
            "type": "STOP_MARKET",
            "stopPrice": stop_price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
        }

        cls._add_position_side(
            payload,
            context.position_side,
        )

        log(
            f"[EXECUTOR] {context.symbol} | "
            f"SL {context.exit_side} stopPrice={stop_price}"
        )

        response = client.place_order(payload)
        return response.get("orderId")

    @classmethod
    def _place_tp1(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
        context: ExecutionContext,
        filled_qty: float,
    ) -> int | str | None:
        raw_tp1_qty = (
            plan.tp1_qty
            if plan.tp1_qty is not None
            else filled_qty * settings.EXECUTOR_TP1_FRAC
        )

        tp1_qty = client.normalize_qty(
            context.symbol,
            raw_tp1_qty,
        )

        if tp1_qty <= 0:
            log(
                f"[EXECUTOR] {context.symbol} | "
                "TP1 skipped because normalized quantity is zero"
            )
            return None

        tp1_price = client.normalize_price(
            context.symbol,
            plan.tp1,
        )

        payload: dict[str, Any] = {
            "symbol": context.symbol,
            "side": context.exit_side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": tp1_price,
            "quantity": tp1_qty,
            "workingType": "MARK_PRICE",
        }

        cls._add_position_side(
            payload,
            context.position_side,
        )

        log(
            f"[EXECUTOR] {context.symbol} | "
            f"TP1 {context.exit_side} "
            f"stopPrice={tp1_price} qty={tp1_qty}"
        )

        response = client.place_order(payload)
        return response.get("orderId")

    @classmethod
    def _save_entry_snapshot(
        cls,
        plan: OrderPlan,
        symbol: str,
        direction: str,
    ) -> None:
        snapshot = build_entry_snapshot(
            plan.market_state,
            plan.features,
            symbol=symbol,
            side=direction,
            strategy_setup=plan.setup_type,
        )

        save_entry_snapshot(snapshot)

    @classmethod
    def _build_position_data(
        cls,
        client: BinanceFuturesClient,
        plan: OrderPlan,
        context: ExecutionContext,
        entry: EntryFill,
        protective_orders: ProtectiveOrders,
    ) -> dict[str, Any]:
        leverage = cls._get_leverage()

        size_usdt = (
            float(plan.notional)
            if plan.notional
            else entry.qty * entry.price
        )
        margin_usdt = size_usdt / leverage

        sl_pct = cls._price_change_percent(
            entry_price=entry.price,
            target_price=plan.stop_loss,
            direction=context.direction,
            favorable=False,
        )
        tp1_pct = cls._price_change_percent(
            entry_price=entry.price,
            target_price=plan.tp1,
            direction=context.direction,
            favorable=True,
        )
        tp2_pct = cls._price_change_percent(
            entry_price=entry.price,
            target_price=plan.tp2,
            direction=context.direction,
            favorable=True,
        )
        tp3_pct = cls._price_change_percent(
            entry_price=entry.price,
            target_price=plan.tp3,
            direction=context.direction,
            favorable=True,
        )

        return {
            "status": "Open",
            "symbol": context.symbol,
            "side": context.direction,
            "strategy": plan.strategy_family or "trend_following",
            "setup": plan.setup_type,
            "size_usdt": round(size_usdt, 2),
            "margin_usdt": round(margin_usdt, 2),
            "entry": entry.price,
            "entry_qty": entry.qty,
            "pos_side": context.position_side,
            "stop_loss": {
                "price": plan.stop_loss,
                "percent": round(sl_pct, 2),
                "risk_usdt": plan.risk_amount,
                "sl_order_id": protective_orders.stop_loss_order_id,
                "sl_hit": False,
            },
            "take_profit": [
                cls._build_take_profit_record(
                    name="tp1",
                    partial_close=50.0,
                    price=plan.tp1,
                    percent=tp1_pct,
                    order_id=protective_orders.tp1_order_id,
                ),
                cls._build_take_profit_record(
                    name="tp2",
                    partial_close=30.0,
                    price=plan.tp2,
                    percent=tp2_pct,
                    order_id=None,
                ),
                cls._build_take_profit_record(
                    name="tp3",
                    partial_close=20.0,
                    price=plan.tp3,
                    percent=tp3_pct,
                    order_id=None,
                ),
            ],
            "pnl_usdt": 0.0,
            "exchange_pnl_usdt": None,
            "balance_usdt": client.get_balance("USDT"),
            "closed_reason": None,
            "opened": datetime.now(timezone.utc).isoformat(),
            "closed": None,
        }

    @staticmethod
    def _build_take_profit_record(
        *,
        name: str,
        partial_close: float,
        price: float,
        percent: float,
        order_id: int | str | None,
    ) -> dict[str, Any]:
        return {
            f"{name}_partial_close": partial_close,
            f"{name}_hit": False,
            "price": price,
            "percent": round(percent, 2),
            f"{name}_order_id": order_id,
        }

    @staticmethod
    def _price_change_percent(
        *,
        entry_price: float,
        target_price: float,
        direction: str,
        favorable: bool,
    ) -> float:
        if entry_price <= 0:
            return 0.0

        if direction == "LONG":
            difference = (
                target_price - entry_price
                if favorable
                else entry_price - target_price
            )
        else:
            difference = (
                entry_price - target_price
                if favorable
                else target_price - entry_price
            )

        return difference / entry_price * 100

    @staticmethod
    def _resolve_fill_price(
        *,
        response: dict[str, Any],
        fallback_price: float,
    ) -> float:
        avg_price = float(response.get("avgPrice") or 0)

        if avg_price > 0:
            return avg_price

        fills = response.get("fills") or []

        total_qty = sum(
            float(fill.get("qty") or 0)
            for fill in fills
        )
        total_value = sum(
            float(fill.get("qty") or 0)
            * float(fill.get("price") or 0)
            for fill in fills
        )

        if total_qty > 0:
            return total_value / total_qty

        return float(fallback_price)

    @staticmethod
    def _resolve_filled_qty(
        *,
        response: dict[str, Any],
        fallback_qty: float,
    ) -> float:
        executed_qty = float(response.get("executedQty") or 0)

        if executed_qty > 0:
            return executed_qty

        fills = response.get("fills") or []
        fills_qty = sum(
            float(fill.get("qty") or 0)
            for fill in fills
        )

        return fills_qty if fills_qty > 0 else float(fallback_qty)

    @staticmethod
    def _add_position_side(
        payload: dict[str, Any],
        position_side: str | None,
    ) -> None:
        if position_side:
            payload["positionSide"] = position_side

    @staticmethod
    def _get_leverage() -> float:
        leverage = float(settings.LEVERAGE or 1)

        if leverage <= 0:
            raise ValueError(
                f"LEVERAGE must be greater than zero, got {leverage}"
            )

        return leverage