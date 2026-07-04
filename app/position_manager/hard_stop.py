from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from config import settings
from position_management.staged import ManagedPosition


def planned_max_loss_usd(notional_usdt: float, entry: float, stop: float) -> float:
    """planned_risk = notional * SL distance (fraction), SL distance = |entry - stop| / entry."""
    en = max(float(entry), 1e-12)
    return float(notional_usdt) * abs(float(entry) - float(stop)) / en


def max_loss_allowed(pos: ManagedPosition) -> float:
    """Remaining open leg cap: full-trade planned max loss scaled by qty_open / qty_total."""
    full = float(getattr(pos, "max_hard_stop_loss_usd", 0.0) or 0.0)
    if full <= 0.0:
        full = float(pos.initial_risk_usd or 0.0)
    if full <= 0.0:
        return 0.0
    qt = max(float(pos.qty_total), 1e-12)
    qo = max(float(pos.qty_open), 0.0)
    return full * (qo / qt)


@dataclass(frozen=True)
class HardStopDecision:
    triggered: bool
    reason: str
    trigger_price: float
    max_loss_allowed_usd: float
    unrealized_pnl_at_trigger: float
    used_stale_mark_guard: bool = False
    abnormal_slippage_guard: bool = False


def hit_stop_price(
    *,
    pos: ManagedPosition,
    mark_price: float,
    stop_buffer_frac: float = 0.0,
) -> tuple[bool, float]:
    """
    Hard-stop signal using exchange mark price.
    LONG: mark_price <= stop*(1+buffer), SHORT: mark_price >= stop*(1-buffer)
    """
    if pos.closed or float(pos.qty_open) <= 0.0:
        return False, float(getattr(pos, "current_stop_loss", 0.0) or 0.0)
    stop_px = float(getattr(pos, "current_stop_loss", 0.0) or 0.0)
    if stop_px <= 0.0:
        return False, stop_px
    buf = max(0.0, float(stop_buffer_frac))
    mark = float(mark_price)
    if str(pos.direction).upper() == "LONG":
        trigger_level = stop_px * (1.0 + buf)
        if mark <= trigger_level:
            return True, mark
    else:
        trigger_level = stop_px * (1.0 - buf)
        if mark >= trigger_level:
            return True, mark
    return False, stop_px


def emergency_pnl_kill_switch(
    *,
    pos: ManagedPosition,
    mark_price: float,
) -> tuple[bool, float, float]:
    """
    Secondary backup protection when price-based stop signal is unavailable.
    Returns: (triggered, unrealized_pnl, max_loss_cap)
    """
    if pos.closed or float(pos.qty_open) <= 0.0:
        return False, 0.0, 0.0
    cap = max_loss_allowed(pos)
    if cap <= 0.0:
        return False, 0.0, 0.0
    entry = float(pos.entry)
    qty = float(pos.qty_open)
    mark = float(mark_price)
    if str(pos.direction).upper() == "LONG":
        unreal = (mark - entry) * qty
    else:
        unreal = (entry - mark) * qty
    return float(unreal) <= -cap, float(unreal), float(cap)


def price_trigger_suppressed_after_tp2(
    pos: ManagedPosition,
    *,
    wall_ts: float,
    closed_bar_ts: float | None,
    grace_sec: float,
    skip_same_bar: bool = True,
) -> bool:
    """
    Suppress intrabar price hard-stop after TP2 so the runner uses ATR trail / exchange SL.

    PnL kill-switch is not suppressed.
    """
    if not bool(getattr(pos, "hit_tp2", False)) or float(pos.qty_open) <= 0.0:
        return False
    if bool(getattr(settings, "HARD_STOP_DISABLE_PRICE_ON_RUNNER", True)):
        return True
    tp2_ts = getattr(pos, "tp2_hit_at_ts", None)
    if tp2_ts is None:
        return False
    t2 = float(tp2_ts)
    if skip_same_bar and closed_bar_ts is not None and float(closed_bar_ts) <= t2 + 1e-3:
        return True
    if float(grace_sec) > 0.0 and float(wall_ts) < t2 + float(grace_sec):
        return True
    return False


def _abnormal_slippage_guard(
    *,
    pos: ManagedPosition,
    trigger_price: float,
    max_slippage_r: float,
) -> bool:
    """Flags catastrophic stop gap/slippage distance in R units."""
    r_px = abs(float(pos.entry) - float(pos.stop_loss))
    if r_px <= 1e-12:
        return False
    slip_px = abs(float(trigger_price) - float(getattr(pos, "current_stop_loss", pos.stop_loss)))
    return (slip_px / r_px) >= max(0.0, float(max_slippage_r))


def evaluate_hard_stop(
    *,
    pos: ManagedPosition,
    mark_price: float,
    exchange_sl_active: bool,
    stop_buffer_frac: float = 0.0,
    max_slippage_r: float = 4.0,
) -> HardStopDecision:
    """
    Hard stop is a fallback when exchange SL is not active.
    1) Exchange SL active → no hard stop (exchange handles it)
    2) Exchange SL not active → check mark price breach against stop
    3) PnL kill-switch fallback (backup)
    """
    if pos.closed or float(pos.qty_open) <= 0.0:
        return HardStopDecision(
            triggered=False,
            reason="closed",
            trigger_price=float(mark_price),
            max_loss_allowed_usd=0.0,
            unrealized_pnl_at_trigger=0.0,
        )
    if exchange_sl_active:
        return HardStopDecision(
            triggered=False,
            reason="exchange_sl_active",
            trigger_price=float(mark_price),
            max_loss_allowed_usd=float(max_loss_allowed(pos)),
            unrealized_pnl_at_trigger=0.0,
        )
    hit, trigger_px = hit_stop_price(
        pos=pos,
        mark_price=mark_price,
        stop_buffer_frac=stop_buffer_frac,
    )
    if hit:
        _, unreal, cap = emergency_pnl_kill_switch(pos=pos, mark_price=float(trigger_px))
        abnormal = _abnormal_slippage_guard(
            pos=pos,
            trigger_price=float(trigger_px),
            max_slippage_r=max_slippage_r,
        )
        return HardStopDecision(
            triggered=True,
            reason="hard_stop_price_trigger",
            trigger_price=float(trigger_px),
            max_loss_allowed_usd=float(cap),
            unrealized_pnl_at_trigger=float(unreal),
            abnormal_slippage_guard=bool(abnormal),
        )
    triggered, unreal, cap = emergency_pnl_kill_switch(pos=pos, mark_price=float(mark_price))
    return HardStopDecision(
        triggered=bool(triggered),
        reason=("hard_stop_pnl_kill_switch" if triggered else "hold"),
        trigger_price=float(mark_price),
        max_loss_allowed_usd=float(cap),
        unrealized_pnl_at_trigger=float(unreal),
        abnormal_slippage_guard=False,
    )


def check_hard_stop(pos: ManagedPosition, unrealized_pnl: float) -> bool:
    """Legacy compatibility gate."""
    if pos.closed or float(pos.qty_open) <= 0.0:
        return False
    cap = max_loss_allowed(pos)
    if cap <= 0.0:
        return False
    return float(unrealized_pnl) <= -cap


def force_close_position(
    engine: Any,
    pos: ManagedPosition,
    *,
    side: str,
    qty: float,
    retries: int = 2,
    retry_sleep_sec: float = 0.2,
) -> dict[str, Any] | None:
    """
    Safe reduce-only market close with tiny retry budget.
    Prevents one-shot failure from leaving a hard-stop position unmanaged.
    """
    last_resp: dict[str, Any] | None = None
    for attempt in range(max(1, int(retries))):
        last_resp = engine.close_order(str(pos.symbol), str(side), float(qty))
        if last_resp is not None:
            return last_resp
        if attempt + 1 < max(1, int(retries)):
            time.sleep(max(0.0, float(retry_sleep_sec)))
    return last_resp
