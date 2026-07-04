from __future__ import annotations

import pytest
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.position_management.post_tp1_stop import (
    DEFAULT_TP1_STOP_BUFFER_PERCENT,
    apply_post_tp1_stop_loss,
    compute_post_tp1_stop_price,
    resolve_tp1_stop_buffer_percent,
)
from app.position_management.staged import ManagedPosition, apply_staged_management


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


class TestPostTp1StopBuffer:
    def test_default_long_breakeven_at_entry(self) -> None:
        assert compute_post_tp1_stop_price(100.0, "LONG") == pytest.approx(100.1)

    def test_default_short_breakeven_at_entry(self) -> None:
        assert compute_post_tp1_stop_price(100.0, "SHORT") == pytest.approx(99.9)

    def test_optional_buffer_percent(self) -> None:
        assert compute_post_tp1_stop_price(100.0, "LONG", buffer_percent=0.3) == pytest.approx(100.3)
        assert compute_post_tp1_stop_price(100.0, "SHORT", buffer_percent=0.3) == pytest.approx(99.7)

    def test_default_buffer_is_0_1_percent(self) -> None:
        assert resolve_tp1_stop_buffer_percent("TAOUSDT") == 0.1
        assert resolve_tp1_stop_buffer_percent("UNKNOWN") == DEFAULT_TP1_STOP_BUFFER_PERCENT
        assert DEFAULT_TP1_STOP_BUFFER_PERCENT == 0.1

    def test_never_loosens_long_stop(self) -> None:
        pos = ManagedPosition(
            symbol="TAOUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=0.5,
            entry=100.0,
            stop_loss=99.0,
            current_stop_loss=100.5,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
        )
        pos.hit_tp1 = True
        apply_post_tp1_stop_loss(pos, buffer_percent=0.3)
        assert pos.current_stop_loss == 100.5

    def test_never_loosens_short_stop(self) -> None:
        pos = ManagedPosition(
            symbol="TAOUSDT",
            direction="SHORT",
            qty_total=1.0,
            qty_open=0.5,
            entry=100.0,
            stop_loss=101.0,
            current_stop_loss=99.5,
            tp1=99.0,
            tp2=98.0,
            tp3=97.0,
        )
        pos.hit_tp1 = True
        apply_post_tp1_stop_loss(pos, buffer_percent=0.3)
        assert pos.current_stop_loss == 99.5

    def test_tp1_hit_moves_sl_to_entry(self) -> None:
        pos = ManagedPosition(
            symbol="TAOUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=1.0,
            entry=100.0,
            stop_loss=99.0,
            current_stop_loss=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
        )
        apply_staged_management(pos, high=101.2, low=99.8, pnl_fn=_pnl)
        assert pos.hit_tp1
        assert pos.current_stop_loss == pytest.approx(100.1)

    def test_retouch_entry_does_not_stop_long(self) -> None:
        pos = ManagedPosition(
            symbol="RENDERUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=1.0,
            entry=100.0,
            stop_loss=99.0,
            current_stop_loss=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
        )
        apply_staged_management(pos, high=101.2, low=99.8, pnl_fn=_pnl)
        assert pos.current_stop_loss == pytest.approx(100.1)
        fills = apply_staged_management(pos, high=101.5, low=100.11, pnl_fn=_pnl)
        assert not any(f.tag == "SL HIT" for f in fills)
        assert pos.qty_open > 0
