from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.position_management.staged import ManagedPosition, apply_staged_management


pytestmark = pytest.mark.unit


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def _df15() -> pd.DataFrame:
    rows = []
    for i in range(30):
        low = 100.0 + i * 0.3
        high = low + 1.0
        rows.append({"open": low, "high": high, "low": low, "close": high - 0.1, "volume": 1.0})
    return pd.DataFrame(rows)


def test_tp2_hit_seeds_structure_trail(monkeypatch) -> None:
    from app.position_management import staged as staged_mod

    messages: list[str] = []
    monkeypatch.setattr(staged_mod, "log", lambda m: messages.append(str(m)))

    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=1.0,
        qty_open=0.5,
        entry=100.0,
        stop_loss=99.0,
        current_stop_loss=100.4,
        tp1=101.0,
        tp2=102.0,
        tp3=0.0,
        hit_tp1=True,
    )
    fills = apply_staged_management(
        pos,
        high=102.2,
        low=101.5,
        now_ts=850.0,
        pnl_fn=_pnl,
        df15=_df15(),
    )
    assert any(f.tag == "TP2 HIT" for f in fills)
    assert float(pos.tp3_trailing_stop) >= 100.4
    assert messages == []
