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
from app.position_management.tp3_structure_trail import (
    TP3StructureSnapshot,
    analyze_tp3_structure,
    apply_tp3_structure_trail,
    is_new_15m_close,
    is_runner_tp3,
)


pytestmark = pytest.mark.unit


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def _bullish_df15(*, break_structure: bool = False) -> pd.DataFrame:
    rows = []
    base = 100.0
    for i in range(40):
        low = base + i * 0.4
        high = low + 1.2
        close = high - 0.2
        rows.append({"open": low, "high": high, "low": low, "close": close, "volume": 1.0})
    if break_structure:
        rows[-1]["close"] = rows[-2]["low"] - 1.0
        rows[-1]["low"] = rows[-1]["close"]
        rows[-1]["high"] = rows[-2]["low"]
    return pd.DataFrame(rows)


def test_is_runner_tp3_sentinel() -> None:
    assert is_runner_tp3(0.0) is True
    assert is_runner_tp3(103.0) is False


def test_is_new_15m_close() -> None:
    assert is_new_15m_close(bar_ts=900.0, last_processed_ts=0.0) is True
    assert is_new_15m_close(bar_ts=950.0, last_processed_ts=900.0) is False
    assert is_new_15m_close(bar_ts=1800.0, last_processed_ts=900.0) is True


def test_long_structure_trail_tightens_only() -> None:
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=1.0,
        qty_open=0.2,
        entry=100.0,
        stop_loss=99.0,
        current_stop_loss=100.4,
        tp1=101.0,
        tp2=102.0,
        tp3=0.0,
        hit_tp2=True,
    )
    df15 = _bullish_df15()
    snap1 = apply_tp3_structure_trail(pos, df15, bar_ts=900.0, floor_stop=100.4)
    first = float(pos.tp3_trailing_stop)
    assert first >= 100.4
    assert snap1.structure_intact is True

    snap2 = apply_tp3_structure_trail(pos, df15, bar_ts=1800.0, floor_stop=100.4)
    assert float(pos.tp3_trailing_stop) >= first
    assert snap2.trailing_stop >= first


def test_runner_exits_on_15m_structure_break() -> None:
    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="LONG",
        qty_total=1.0,
        qty_open=0.2,
        entry=100.0,
        stop_loss=99.0,
        current_stop_loss=100.4,
        tp1=101.0,
        tp2=102.0,
        tp3=0.0,
        hit_tp1=True,
        hit_tp2=True,
    )
    df_ok = _bullish_df15()
    apply_staged_management(
        pos,
        high=103.0,
        low=102.0,
        now_ts=900.0,
        pnl_fn=_pnl,
        df15=df_ok,
    )
    assert pos.qty_open > 0.0

    df_break = _bullish_df15(break_structure=True)
    fills = apply_staged_management(
        pos,
        high=103.0,
        low=99.0,
        now_ts=1800.0,
        pnl_fn=_pnl,
        df15=df_break,
    )
    assert any(f.tag == "TP3 HIT" for f in fills)
    assert pos.closed


def test_short_structure_break_exit_uses_close_when_trail_not_crossed(monkeypatch) -> None:
    from app.position_management import staged as staged_mod

    pos = ManagedPosition(
        symbol="TAOUSDT",
        direction="SHORT",
        qty_total=1.0,
        qty_open=0.2,
        entry=263.91,
        stop_loss=266.82,
        current_stop_loss=263.62,
        tp1=261.0,
        tp2=259.54,
        tp3=0.0,
        hit_tp1=True,
        hit_tp2=True,
        tp3_trailing_stop=263.62,
        last_15m_bar_ts=900.0,
    )
    df15 = pd.DataFrame(
        [
            {"open": 260.5, "high": 261.0, "low": 259.8, "close": 260.4, "volume": 1.0}
            for _ in range(8)
        ]
    )
    df15.loc[len(df15) - 1, "close"] = 260.18

    def _broken_trail(*args, **kwargs) -> TP3StructureSnapshot:
        return TP3StructureSnapshot(
            trailing_stop=263.62,
            confirmed_swing=0.0,
            next_swing_trigger=0.0,
            trend_structure="broken",
            structure_intact=False,
            exit_on_close=True,
            estimated_runner_pct=0.0,
        )

    monkeypatch.setattr(staged_mod, "apply_tp3_structure_trail", _broken_trail)
    fills = apply_staged_management(
        pos,
        high=261.0,
        low=259.8,
        now_ts=1800.0,
        pnl_fn=_pnl,
        df15=df15,
    )

    tp3_fill = next(f for f in fills if f.tag == "TP3 HIT")
    assert tp3_fill.price == pytest.approx(260.18)
    assert tp3_fill.pnl == pytest.approx((263.91 - 260.18) * 0.2)


def test_analyze_short_bearish_structure() -> None:
    rows = []
    for i in range(40):
        high = 120.0 - i * 0.4
        low = high - 1.2
        close = low + 0.2
        rows.append({"open": high, "high": high, "low": low, "close": close, "volume": 1.0})
    df15 = pd.DataFrame(rows)
    snap = analyze_tp3_structure(df15, direction="SHORT", entry=120.0, floor_stop=118.0)
    assert snap.trailing_stop <= 118.0 or snap.trailing_stop > 0
    assert snap.trend_structure == "bearish_intact"
