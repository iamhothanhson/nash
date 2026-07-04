from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from position_management.staged import ManagedPosition, apply_staged_management


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def test_exchange_tp1_keeps_runner_when_qty_already_partial(monkeypatch) -> None:
    """Exchange TP1 fill already reduced qty_open; bot must not CLOSE the runner."""
    monkeypatch.setattr(
        "position_management.staged.exchange_tp_detect_by_order_status_enabled",
        lambda: False,
    )
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=10.0,
        qty_open=5.0,
        entry=237.15,
        stop_loss=240.0,
        current_stop_loss=240.0,
        tp1=232.99,
        tp2=228.0,
        tp3=0.0,
        exchange_tp_orders_placed=True,
        exchange_tp1_order_id=9001,
    )
    fills = apply_staged_management(
        pos,
        high=236.0,
        low=232.0,
        now_ts=1_700_000.0,
        pnl_fn=_pnl,
    )
    tp1 = next((f for f in fills if f.tag == "TP1 HIT"), None)
    assert tp1 is not None
    assert tp1.qty_remaining > 0.0
    assert not any(f.tag == "CLOSE" for f in fills)
    assert not pos.closed
    assert pos.qty_open == 5.0
    assert pos.hit_tp1


def test_software_tp1_still_closes_when_no_exchange_tp_order() -> None:
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=10.0,
        qty_open=5.0,
        entry=237.15,
        stop_loss=240.0,
        current_stop_loss=240.0,
        tp1=232.99,
        tp2=228.0,
        tp3=0.0,
    )
    fills = apply_staged_management(
        pos,
        high=236.0,
        low=232.0,
        now_ts=1_700_000.0,
        pnl_fn=_pnl,
    )
    assert any(f.tag == "TP1 HIT" for f in fills)
    assert any(f.tag == "CLOSE" for f in fills)
    assert pos.closed
