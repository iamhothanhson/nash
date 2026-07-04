from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from position_management.staged import ManagedPosition
from reconciliation.exchange_trades import _exchange_flat_close_fallback_fill


class _Engine:
    _client = None


def test_flat_close_fallback_does_not_label_post_tp1_as_sl_without_trigger() -> None:
    pos = ManagedPosition(
        symbol="RENDERUSDT",
        direction="LONG",
        qty_total=12.0,
        qty_open=6.0,
        entry=1.655,
        stop_loss=1.637,
        current_stop_loss=1.657,
        tp1=1.676,
        tp2=1.686,
        tp3=0.0,
        hit_tp1=True,
    )
    fill = _exchange_flat_close_fallback_fill(_Engine(), pos)
    assert fill["is_stop"] is False
    assert float(fill["trigger_price"]) == pytest.approx(1.657)
