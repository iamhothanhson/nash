"""Place reduce-only LIMIT take-profit orders on the exchange after entry."""

from __future__ import annotations

from typing import Any

from config import settings
from execution.position_mode import position_side_for_reduce_order
from monitoring.logger import log as daily_log

TP2_ORDER_KIND_TAKE_PROFIT_MARKET = "take_profit_market"


def normalize_exchange_tp2_order_kind(order_kind: str | None) -> str:
    """Map placement label to persisted kind (only TAKE_PROFIT_MARKET supported)."""
    if not str(order_kind or "").strip():
        return ""
    return TP2_ORDER_KIND_TAKE_PROFIT_MARKET


def _order_id(resp: dict[str, Any] | None) -> int | None:
    if not isinstance(resp, dict):
        return None
    for key in ("orderId", "algoId"):
        raw = resp.get(key)
        if raw is None:
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            continue
    return None


def resolve_tp2_order_qty(
    *,
    symbol: str,
    qty_total: float,
    qty_open: float,
    tp2_close_frac: float,
    client: Any,
) -> float:
    """TP2 leg size from original ``qty_total`` fractions, capped to ``qty_open``."""
    sym_u = str(symbol).strip().upper()
    base = max(0.0, float(qty_total))
    open_q = max(0.0, float(qty_open))
    if base <= 1e-12 or open_q <= 1e-12:
        return 0.0
    f2 = max(0.0, min(1.0, float(tp2_close_frac)))
    q2 = float(client.normalize_qty(sym_u, base * f2))
    if q2 > open_q + 1e-12:
        q2 = float(client.normalize_qty(sym_u, open_q))
    return max(0.0, q2)


def place_tp_limit_orders_after_entry(
    client: Any,
    *,
    symbol: str,
    entry_side: str,
    total_qty: float,
    tp1: float,
    tp2: float,
    tp1_close_frac: float,
    tp2_close_frac: float,
) -> dict[str, Any]:
    """
    Submit TP1 reduce-only LIMIT at entry. TP2 is placed after TP1 fills (see
    ``place_tp2_limit_after_tp1``) so breakeven SL sync does not knockout TP2.
    """
    _ = tp2
    _ = tp2_close_frac
    sym_u = str(symbol).strip().upper()
    sd = str(entry_side).strip().upper()
    close_side = "SELL" if sd in ("BUY", "LONG") else "BUY"
    leg = (
        position_side_for_reduce_order(close_side)
        if client.use_hedge_position_side()
        else None
    )

    try:
        pos_amt = abs(float(client.get_position_amount(sym_u, leg)))
    except Exception:
        pos_amt = abs(float(total_qty))
    base_qty = pos_amt if pos_amt > 1e-12 else abs(float(total_qty))
    if base_qty <= 1e-12:
        return {"placed": False, "reason": "no_position_qty"}

    f1 = max(0.0, min(1.0, float(tp1_close_frac)))
    q1 = float(client.normalize_qty(sym_u, base_qty * f1))

    out: dict[str, Any] = {
        "placed": False,
        "tp1_order_id": None,
        "tp2_order_id": None,
        "tp1_qty": q1,
        "tp2_qty": 0.0,
    }
    errors: list[str] = []

    if q1 > 0.0 and float(tp1) > 0.0:
        try:
            r1 = client.create_reduce_only_limit_order(
                sym_u, close_side, q1, float(tp1), position_side=leg
            )
            out["tp1_order_id"] = _order_id(r1)
            daily_log(
                f"[TP1 ORDER] {sym_u} | LIMIT {close_side} qty={q1:.8g} @ {float(tp1):.8g} | "
                f"orderId={out['tp1_order_id']}"
            )
        except Exception as exc:
            errors.append(f"TP1: {exc}")

    if out["tp1_order_id"] is not None:
        out["placed"] = True
    if errors:
        out["errors"] = errors
        daily_log(f"[TP1 ORDER WARN] {sym_u} | {'; '.join(errors)}")
    return out


def place_tp2_limit_after_tp1(client: Any, pos: Any) -> dict[str, Any]:
    """Place TP2 on exchange after TP1 (conditional TAKE_PROFIT_MARKET algo order)."""
    sym_u = str(getattr(pos, "symbol", "")).strip().upper()
    direction = str(getattr(pos, "direction", "")).strip().upper()
    close_side = "SELL" if direction == "LONG" else "BUY"
    leg = (
        position_side_for_reduce_order(close_side)
        if client.use_hedge_position_side()
        else None
    )
    tp2_px = float(getattr(pos, "tp2", 0.0) or 0.0)
    q2 = resolve_tp2_order_qty(
        symbol=sym_u,
        qty_total=float(getattr(pos, "qty_total", 0.0)),
        qty_open=float(getattr(pos, "qty_open", 0.0)),
        tp2_close_frac=float(getattr(pos, "tp2_close_frac", 0.30)),
        client=client,
    )
    out: dict[str, Any] = {
        "placed": False,
        "tp2_order_id": None,
        "tp2_qty": q2,
    }
    if q2 <= 0.0 or tp2_px <= 0.0:
        out["reason"] = "no_tp2_qty"
        return out
    order_kind = "CONDITIONAL TAKE_PROFIT_MARKET"
    try:
        r2 = client.create_conditional_take_profit_market_order(
            sym_u, close_side, q2, tp2_px, position_side=leg
        )
    except Exception as exc:
        out["errors"] = [str(exc)]
        daily_log(f"[TP2 ORDER WARN] {sym_u} | after TP1 failed | {exc}")
        return out
    out["tp2_order_id"] = _order_id(r2)
    out["tp2_order_kind"] = normalize_exchange_tp2_order_kind(order_kind)
    out["placed"] = out["tp2_order_id"] is not None
    daily_log(
        f"[TP2 ORDER] {sym_u} | {order_kind} (after TP1) {close_side} qty={q2:.8g} @ {tp2_px:.8g} | "
        f"orderId={out['tp2_order_id']} | kind={out['tp2_order_kind'] or 'unknown'}"
    )
    return out


def exchange_tp2_after_tp1_enabled() -> bool:
    """When true (default), place TP2 on exchange after TP1; BE stop remains closePosition."""
    if not exchange_tp_orders_enabled():
        return False
    return bool(getattr(settings, "EXCHANGE_TP2_AFTER_TP1", True))


def ensure_exchange_tp2_after_tp1(engine: Any, pos: Any) -> bool:
    """
    Place deferred TP2 on the exchange after TP1 hit.

    When ``EXCHANGE_TP2_AFTER_TP1`` is true (default). Call after BE stop sync so both
    conditional orders can coexist (closePosition BE stop + TP2 reduce-only leg).
    """
    if not exchange_tp2_after_tp1_enabled():
        return False
    if not bool(getattr(pos, "exchange_tp_orders_placed", False)):
        return False
    if not bool(getattr(pos, "hit_tp1", False)):
        return False
    if bool(getattr(pos, "hit_tp2", False)) or bool(getattr(pos, "closed", False)):
        return False
    if float(getattr(pos, "qty_open", 0.0) or 0.0) <= 1e-12:
        return False
    if getattr(pos, "exchange_tp2_order_id", None) is not None:
        return False
    client = getattr(engine, "_client", None)
    if client is None:
        return False
    meta = place_tp2_limit_after_tp1(client, pos)
    oid = meta.get("tp2_order_id")
    if oid is None:
        return False
    pos.exchange_tp2_order_id = int(oid)
    pos.exchange_tp2_order_kind = TP2_ORDER_KIND_TAKE_PROFIT_MARKET
    return True


def exchange_tp_orders_enabled() -> bool:
    mode = str(settings.MODE).strip().lower()
    if mode not in ("live", "demo"):
        return False
    return bool(getattr(settings, "EXCHANGE_TP_ORDERS_ON_OPEN", True))


def exchange_tp_detect_by_order_status_enabled() -> bool:
    if not exchange_tp_orders_enabled():
        return False
    return bool(getattr(settings, "EXCHANGE_TP_DETECT_BY_ORDER_STATUS", True))
