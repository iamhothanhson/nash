from __future__ import annotations

import time

from config import settings
from execution.exchange_client import BinanceExchangeClient, BinanceOrderError
from execution.position_mode import position_side_for_direction
from monitoring.logger import log as daily_log
from position_management.staged import ManagedPosition
from common.rounding import format_price, round_price, round_qty, round_usd
from coins.loader import price_rounding_decimal
from monitoring.messages import format_post_tp2_exchange_sl_placed_line
from monitoring.notifier import send_alert
from execution.cancel_position_orders import cancel_orders_for_flat_position_if_live
from position_management.post_tp1_stop import is_post_tp1_protected_stop


def _protective_side(direction: str) -> str:
    return "SELL" if str(direction).upper() == "LONG" else "BUY"


def _parse_order_id(resp: dict | None) -> int | None:
    if not isinstance(resp, dict):
        return None
    oid = resp.get("orderId")
    if oid is None:
        return None
    try:
        return int(oid)
    except (TypeError, ValueError):
        return None


def _cancel_stop_if_known(
    client: BinanceExchangeClient,
    symbol: str,
    order_id: int | None,
) -> None:
    if order_id is None:
        return
    sym_u = symbol.strip().upper()
    try:
        client.cancel_futures_stop_order(sym_u, int(order_id))
        daily_log(f"[SL SYNC] {sym_u} | Canceled Stop | orderId={order_id}")
    except BinanceOrderError as exc:
        if exc.code in (-2011, -2013):
            daily_log(f"[SL SYNC] {sym_u} | Cancel Skip (order gone) | orderId={order_id} | {exc.msg}")
            return
        daily_log(f"[SL SYNC] {sym_u} | Cancel FAILED | orderId={order_id} | {exc.msg}")
        raise
    except Exception as exc:
        daily_log(f"[SL SYNC] {sym_u} | Cancel FAILED | orderId={order_id} | {exc}")
        raise


def _stop_price_tolerance(client: BinanceExchangeClient, sym_u: str) -> float:
    tick = client.price_tick_size(sym_u)
    return max(tick * 0.5, 1e-12)


def _normalized_exchange_stop(
    client: BinanceExchangeClient,
    sym_u: str,
    stop_price: float,
) -> float:
    if float(stop_price) <= 0.0:
        return 0.0
    return float(client.normalize_stop_price(sym_u, float(stop_price)))


def _stop_prices_equivalent_on_exchange(
    client: BinanceExchangeClient,
    sym_u: str,
    target_stop: float,
    sent_stop: float,
) -> bool:
    """True when both stops map to the same exchange tick (avoids cancel/replace noise)."""
    if float(sent_stop) <= 0.0:
        return False
    tol_p = _stop_price_tolerance(client, sym_u)
    n_target = _normalized_exchange_stop(client, sym_u, target_stop)
    n_sent = _normalized_exchange_stop(client, sym_u, sent_stop)
    return abs(n_target - n_sent) <= tol_p


def _runner_dust_notional(
    pos: ManagedPosition,
    client: BinanceExchangeClient,
    sym_u: str,
) -> tuple[bool, float]:
    """True when open runner notional is below POSITION_DUST_CLOSE_NOTIONAL_USDT."""
    if not bool(getattr(settings, "POSITION_DUST_CLOSE_ENABLED", True)):
        return False, 0.0
    qty = max(0.0, float(pos.qty_open))
    if qty <= 1e-12:
        return False, 0.0
    threshold = max(0.0, float(getattr(settings, "POSITION_DUST_CLOSE_NOTIONAL_USDT", 7.0)))
    try:
        mark = float(client.get_mark_price(sym_u))
    except Exception:
        mark = float(pos.entry)
    notional = qty * max(0.0, mark)
    return notional <= threshold, notional


def _cancel_stop_state(pos: ManagedPosition) -> None:
    pos.stop_exchange_order_id = None
    pos.last_sent_stop_loss = 0.0
    pos.last_sent_qty_open = 0.0


def _needs_resync(
    pos: ManagedPosition,
    client: BinanceExchangeClient,
    sym_u: str,
    n_stop: float,
    n_qty: float,
) -> bool:
    if n_qty <= 0:
        return False
    if pos.stop_exchange_order_id is None and float(pos.qty_open) > 0:
        return True

    step = client.lot_size_step(sym_u)
    tol_q = max(step * 0.5, 1e-10)

    if pos.last_sent_stop_loss <= 0 and pos.last_sent_qty_open <= 0:
        return True

    price_changed = not _stop_prices_equivalent_on_exchange(
        client,
        sym_u,
        n_stop,
        float(pos.last_sent_stop_loss),
    )
    dq = abs(n_qty - float(pos.last_sent_qty_open))
    return price_changed or dq > tol_q


def _can_start_resync(pos: ManagedPosition) -> bool:
    now_ts = time.time()
    inflight_until = float(getattr(pos, "stop_sync_inflight_until_ts", 0.0) or 0.0)
    return now_ts >= inflight_until


def runner_stop_qty_for_exchange(
    pos: ManagedPosition,
    client: BinanceExchangeClient,
    sym_u: str,
) -> float:
    """
    Qty represented by the protective exchange stop.

    Post-TP1 BE is placed as ``closePosition=true`` so it can coexist with the
    resting TP2 reduce-only order and close whatever size remains at trigger time.
    """
    open_q = max(0.0, float(pos.qty_open))
    if open_q <= 1e-12:
        return 0.0
    return open_q


def exchange_stop_is_active(
    pos: ManagedPosition,
    client: BinanceExchangeClient | None = None,
) -> bool:
    """True when live/demo runner exit should be handled by the synced exchange stop."""
    if settings.MODE not in ("live", "demo"):
        return False
    if pos.closed or float(pos.qty_open) <= 1e-12:
        return False
    sym_u = str(pos.symbol).strip().upper()
    if client is not None:
        is_dust, _ = _runner_dust_notional(pos, client, sym_u)
        if is_dust:
            return False
    if getattr(pos, "stop_exchange_order_id", None) is None:
        return False
    if float(pos.last_sent_stop_loss) <= 0 or float(pos.last_sent_qty_open) <= 0:
        return False
    if client is None:
        return True
    if not _stop_prices_equivalent_on_exchange(
        client,
        sym_u,
        float(pos.current_stop_loss),
        float(pos.last_sent_stop_loss),
    ):
        return False
    sent_qty = float(pos.last_sent_qty_open)
    target_qty = runner_stop_qty_for_exchange(pos, client, sym_u)
    step = client.lot_size_step(sym_u)
    tol_q = max(step * 0.5, 1e-10)
    return abs(sent_qty - target_qty) <= tol_q


def update_stop_on_exchange(
    pos: ManagedPosition,
    client: BinanceExchangeClient,
    *,
    max_place_retries: int = 2,
) -> bool:
    """
    Align Binance reduce-only STOP_MARKET with ManagedPosition.current_stop_loss and qty_open.

    Call after apply_staged_management() (and after partial closes are synced on the exchange).
    """
    if settings.MODE not in ("live", "demo"):
        return True

    sym_u = pos.symbol.strip().upper()

    if pos.closed or bool(getattr(pos, "hit_tp3", False)) or float(pos.qty_open) <= 0:
        reason = "stop_sync_tp3" if bool(getattr(pos, "hit_tp3", False)) else "stop_sync_flat"
        cancel_orders_for_flat_position_if_live(client, pos, reason=reason)
        return True

    is_dust, dust_notional = _runner_dust_notional(pos, client, sym_u)
    if is_dust:
        try:
            _cancel_stop_if_known(client, sym_u, pos.stop_exchange_order_id)
        finally:
            _cancel_stop_state(pos)
        threshold = max(0.0, float(getattr(settings, "POSITION_DUST_CLOSE_NOTIONAL_USDT", 7.0)))
        daily_log(
            f"[SL SYNC] {sym_u} | skip dust runner (notional~{dust_notional:.4f} USDT "
            f"<= {threshold:.2f}) | qty_open={float(pos.qty_open):.8g}"
        )
        return True

    n_stop = client.normalize_stop_price(sym_u, float(pos.current_stop_loss))
    raw_stop_qty = runner_stop_qty_for_exchange(pos, client, sym_u)
    n_qty = client.normalize_qty(sym_u, float(raw_stop_qty))
    if n_qty <= 0:
        if float(pos.qty_open) > 0 and getattr(pos, "exchange_tp2_order_id", None) is not None:
            try:
                _cancel_stop_if_known(client, sym_u, pos.stop_exchange_order_id)
            finally:
                _cancel_stop_state(pos)
            daily_log(
                f"[SL SYNC] {sym_u} | Canceled Stop (open qty covered by TP2 limit) | "
                f"qty_open={float(pos.qty_open):.8g}"
            )
            return True
        daily_log(
            f"[SL SYNC] {sym_u} | skip: normalized stop qty is 0 "
            f"(qty_open={pos.qty_open} runner_stop_qty={raw_stop_qty})"
        )
        return False

    if not _needs_resync(pos, client, sym_u, n_stop, n_qty):
        return True

    # Guard against overlapping cancel/replace calls in volatile loops.
    if not _can_start_resync(pos):
        daily_log(
            f"[SL SYNC] {sym_u} | skip overlapping resync | "
            f"inflight_until={float(getattr(pos, 'stop_sync_inflight_until_ts', 0.0)):.3f}"
        )
        return True

    pos.stop_sync_epoch = int(getattr(pos, "stop_sync_epoch", 0)) + 1
    start_epoch = int(pos.stop_sync_epoch)
    pos.stop_sync_inflight_until_ts = time.time() + 1.0

    protective = _protective_side(pos.direction)
    stop_leg = (
        position_side_for_direction(pos.direction)
        if client.use_hedge_position_side()
        else None
    )
    tick = client.price_tick_size(sym_u)
    open_q = max(0.0, float(pos.qty_open))
    be_stop = is_post_tp1_protected_stop(
        n_stop,
        float(pos.entry),
        pos.direction,
        symbol=sym_u,
        tick_tolerance=tick * 0.5,
    )
    use_close_position = bool(be_stop)
    qty_label = "closePosition" if use_close_position else f"{n_qty:.8g}"


    try:
        _cancel_stop_if_known(client, sym_u, pos.stop_exchange_order_id)
        pos.stop_exchange_order_id = None
        time.sleep(0.1)

        last_exc: Exception | None = None
        for attempt in range(max(1, int(max_place_retries))):
            # If a newer stop intent was created, abort this stale sync worker.
            if int(getattr(pos, "stop_sync_epoch", 0)) != start_epoch:
                daily_log(
                    f"[SL SYNC] {sym_u} | stale stop-sync worker aborted | "
                    f"epoch={start_epoch} current={int(getattr(pos, 'stop_sync_epoch', 0))}"
                )
                return True
            try:
                close_position = use_close_position
                stop_qty = None if close_position else n_qty
                try:
                    resp = client.create_conditional_stop_market_order(
                        sym_u,
                        protective,
                        n_stop,
                        quantity=stop_qty,
                        close_position=close_position,
                        position_side=stop_leg,
                        cancel_all_algo_orders=False,
                    )
                except BinanceOrderError as exc:
                    if close_position and exc.code == -4509 and n_qty > 0:
                        daily_log(
                            f"[SL SYNC] {sym_u} | closePosition rejected (-4509), "
                            f"retry qty={n_qty:.8g} | {exc.msg}"
                        )
                        close_position = False
                        stop_qty = n_qty
                        resp = client.create_conditional_stop_market_order(
                            sym_u,
                            protective,
                            n_stop,
                            quantity=stop_qty,
                            close_position=False,
                            position_side=stop_leg,
                            cancel_all_algo_orders=False,
                        )
                    else:
                        raise
                use_close_position = close_position
                new_id = _parse_order_id(resp)
                pos.stop_exchange_order_id = new_id
                pos.last_sent_stop_loss = n_stop
                pos.last_sent_qty_open = open_q if use_close_position else n_qty
                if be_stop:
                    pd = price_rounding_decimal(sym_u)
                    daily_log(
                        f"[BREAKEVEN] {sym_u} | Move SL to entry on Exchange after TP1 Hit | orderId={new_id} price={n_stop:.8g} | "
                        f"entry={format_price(float(pos.entry), pd)} | qty_remaining={round_qty(open_q, 3):.3f}"
                    )
                else:
                    if bool(getattr(pos, "hit_tp2", False)):
                        pd = price_rounding_decimal(sym_u)
                        size_usdt = round_usd(float(pos.entry) * open_q, 2)
                        sl_line = format_post_tp2_exchange_sl_placed_line(
                            symbol=sym_u,
                            order_id=new_id,
                            stop_price=n_stop,
                            size_usdt=size_usdt,
                            price_decimals=pd,
                        )
                        daily_log(sl_line)
                        send_alert(sl_line)
                    else:
                        daily_log(
                            f"[SL PLACED] {sym_u} | Placed Conditional Stop | orderId={new_id} "
                            f"price={n_stop:.8g} qty={qty_label}"
                        )
                return True
            except BinanceOrderError as exc:
                last_exc = exc
                daily_log(
                    f"[SL SYNC] {sym_u} | place attempt {attempt + 1}/{max_place_retries} failed | {exc.msg}"
                )
                time.sleep(0.2 * (attempt + 1))
            except Exception as exc:
                last_exc = exc
                daily_log(
                    f"[SL SYNC] {sym_u} | place attempt {attempt + 1}/{max_place_retries} failed | {exc}"
                )
                time.sleep(0.2 * (attempt + 1))

        if last_exc is not None:
            daily_log(f"[SL SYNC] {sym_u} | FAILED after retries | {last_exc}")
        return False
    finally:
        # Always release the inflight window quickly.
        pos.stop_sync_inflight_until_ts = 0.0
