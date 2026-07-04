"""Cancel exchange protective / TP orders when a managed position is flat (live/demo)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import settings
from execution.exchange_client import BinanceExchangeClient, BinanceOrderError
from execution.position_mode import position_side_for_direction
from monitoring.logger import log as daily_log
from position_management.staged import ManagedPosition


@dataclass
class PositionOrderCleanupResult:
    reason: str
    canceled_sl: int | None = None
    canceled_tp1: int | None = None
    canceled_tp2: int | None = None
    algo_sweep: bool = False
    errors: list[str] = field(default_factory=list)


def _order_id_from_pos(pos: Any, attr: str) -> int | None:
    raw = getattr(pos, attr, None)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def clear_position_exchange_order_state(pos: ManagedPosition) -> None:
    """Clear runtime order ids only; position history journal rows are unchanged."""
    pos.stop_exchange_order_id = None
    pos.last_sent_stop_loss = 0.0
    pos.last_sent_qty_open = 0.0
    pos.exchange_tp1_order_id = None
    pos.exchange_tp2_order_id = None
    pos.exchange_tp2_order_kind = ""


def _cancel_limit_order(
    client: BinanceExchangeClient,
    sym_u: str,
    order_id: int | None,
    *,
    label: str,
) -> bool:
    if order_id is None:
        return False
    oid = int(order_id)
    try:
        client.cancel_futures_order(sym_u, oid)
        daily_log(f"[ORDER CLEANUP] {sym_u} | canceled {label} | orderId={oid}")
        return True
    except BinanceOrderError as exc:
        if exc.code in (-2011, -2013):
            daily_log(
                f"[ORDER CLEANUP] {sym_u} | cancel skip ({label} gone) | "
                f"orderId={oid} | {exc.msg}"
            )
            return False
        raise
    except Exception as exc:
        daily_log(f"[ORDER CLEANUP] {sym_u} | cancel FAILED {label} | orderId={oid} | {exc}")
        raise


def _cancel_protective_order(
    client: BinanceExchangeClient,
    sym_u: str,
    order_id: int | None,
    *,
    label: str,
) -> bool:
    if order_id is None:
        return False
    oid = int(order_id)
    try:
        client.cancel_futures_stop_order(sym_u, oid)
        daily_log(f"[ORDER CLEANUP] {sym_u} | canceled {label} | orderId={oid}")
        return True
    except BinanceOrderError as exc:
        if exc.code in (-2011, -2013):
            daily_log(
                f"[ORDER CLEANUP] {sym_u} | cancel skip ({label} gone) | "
                f"orderId={oid} | {exc.msg}"
            )
            return False
        raise
    except Exception as exc:
        daily_log(f"[ORDER CLEANUP] {sym_u} | cancel FAILED {label} | orderId={oid} | {exc}")
        raise


def _symbol_flat_on_exchange(client: BinanceExchangeClient, pos: ManagedPosition) -> bool:
    sym_u = str(pos.symbol).strip().upper()
    try:
        if client.use_hedge_position_side():
            leg = position_side_for_direction(str(pos.direction))
            return abs(float(client.get_position_amount(sym_u, leg))) <= 1e-10
        return not bool(client.has_open_position_size(sym_u))
    except Exception as exc:
        daily_log(f"[ORDER CLEANUP] {sym_u} | flat check failed | {exc}")
        return False


def cancel_all_orders_for_flat_position(
    client: BinanceExchangeClient,
    pos: ManagedPosition,
    *,
    reason: str = "position_flat",
) -> PositionOrderCleanupResult:
    """
    Cancel bot-placed SL / TP orders for a closed position.

  Known order ids first; when the exchange reports flat, sweep open conditional algos.
  Does not modify position history journal (order ids remain on the closed row).
    """
    sym_u = str(pos.symbol).strip().upper()
    result = PositionOrderCleanupResult(reason=str(reason).strip() or "position_flat")
    sl_id = _order_id_from_pos(pos, "stop_exchange_order_id")
    tp1_id = _order_id_from_pos(pos, "exchange_tp1_order_id")
    tp2_id = _order_id_from_pos(pos, "exchange_tp2_order_id")

    try:
        if _cancel_limit_order(client, sym_u, tp1_id, label="tp1"):
            result.canceled_tp1 = tp1_id
        if _cancel_protective_order(client, sym_u, tp2_id, label="tp2"):
            result.canceled_tp2 = tp2_id
        if _cancel_protective_order(client, sym_u, sl_id, label="sl"):
            result.canceled_sl = sl_id
        if _symbol_flat_on_exchange(client, pos):
            try:
                client.cancel_all_open_algo_orders(sym_u)
                result.algo_sweep = True
                daily_log(
                    f"[ORDER CLEANUP] {sym_u} | algo open-order sweep | reason={result.reason}"
                )
            except BinanceOrderError as exc:
                daily_log(
                    f"[ORDER CLEANUP] {sym_u} | algo sweep warn | code={exc.code} | {exc.msg}"
                )
            except Exception as exc:
                daily_log(f"[ORDER CLEANUP] {sym_u} | algo sweep failed | {exc}")
        else:
            daily_log(
                f"[ORDER CLEANUP] {sym_u} | skip algo sweep (position not flat on exchange) | "
                f"reason={result.reason}"
            )
    except Exception as exc:
        result.errors.append(str(exc))
        daily_log(f"[ORDER CLEANUP] {sym_u} | partial cleanup | reason={result.reason} | {exc}")

    clear_position_exchange_order_state(pos)
    return result


def cancel_orders_for_flat_position_if_live(
    client: BinanceExchangeClient | None,
    pos: ManagedPosition,
    *,
    reason: str = "position_flat",
) -> PositionOrderCleanupResult | None:
    if settings.MODE not in ("live", "demo") or client is None:
        return None
    return cancel_all_orders_for_flat_position(client, pos, reason=reason)
