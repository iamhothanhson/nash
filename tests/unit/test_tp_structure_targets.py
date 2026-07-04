from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from strategy.tp_structure_targets import (
    _tp3_structure_fallback,
    resolve_tp1_price,
    resolve_tp2_price,
    tp3_from_structure,
    tp_from_r,
)

pytestmark = pytest.mark.unit


def _frame(n: int = 30, *, high_val: float = 120.0) -> pd.DataFrame:
    base = 100.0
    rows = []
    for i in range(n):
        rows.append(
            {
                "open": base,
                "high": high_val if i >= n - 5 else base + 0.5,
                "low": base - 0.5,
                "close": base,
            }
        )
    return pd.DataFrame(rows)


def test_tp_from_r_1r_and_2r() -> None:
    assert tp_from_r(entry=100.0, direction="LONG", dist=0.005, tp_r=1.0) == pytest.approx(100.5)
    assert tp_from_r(entry=100.0, direction="LONG", dist=0.005, tp_r=2.0) == pytest.approx(101.0)
    assert tp_from_r(entry=100.0, direction="SHORT", dist=0.005, tp_r=2.0) == pytest.approx(99.0)


def test_resolve_tp1_and_tp2() -> None:
    tp1 = resolve_tp1_price(entry=100.0, direction="LONG", dist=0.005, tp1_r=1.0)
    tp2 = resolve_tp2_price(entry=100.0, direction="LONG", dist=0.005, tp2_r=2.0)
    assert tp1 == pytest.approx(100.5)
    assert tp2 == pytest.approx(101.0)


def test_long_tp3_picks_swings_beyond_tp2() -> None:
    df = _frame(30, high_val=115.0)
    tp3 = tp3_from_structure(
        entry=100.0,
        direction="LONG",
        data_15m=df,
        tp2=101.0,
        lookback=96,
        sep_frac=0.0015,
    )
    assert tp3 == 115.0


def test_short_tp3_picks_swings_beyond_tp2() -> None:
    n = 30
    rows = []
    for i in range(n):
        rows.append(
            {
                "open": 100.0,
                "high": 100.5,
                "low": 85.0 if i >= n - 5 else 99.0,
                "close": 100.0,
            }
        )
    df = pd.DataFrame(rows)
    tp3 = tp3_from_structure(
        entry=100.0,
        direction="SHORT",
        data_15m=df,
        tp2=99.0,
        lookback=96,
        sep_frac=0.0015,
    )
    assert tp3 == 85.0


def test_short_window_uses_tp3_fallback() -> None:
    df = pd.DataFrame({"open": [100.0], "high": [110.0], "low": [99.0], "close": [100.0]})
    tp3 = _tp3_structure_fallback(entry=100.0, direction="LONG", tp2=101.0, sep_frac=0.0015)
    assert tp3 == pytest.approx(101.0 * 1.0015)
    assert tp3_from_structure(
        entry=100.0,
        direction="LONG",
        data_15m=df,
        tp2=101.0,
        lookback=96,
        sep_frac=0.0015,
    ) == tp3
