from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.backtesting.backtest import _slice_asof_tail_reset_index


@pytest.mark.unit
def test_slice_asof_tail_reset_index_matches_boolean_mask() -> None:
    idx = pd.date_range("2024-01-01", periods=200, freq="5min", tz="UTC")
    df = pd.DataFrame(
        {"open": range(200), "high": range(200), "close": range(200)},
        index=idx,
    )
    ts = idx[120]
    max_rows = 40
    got = _slice_asof_tail_reset_index(df, ts, max_rows)
    want = df[df.index <= ts].tail(max_rows).reset_index()
    pd.testing.assert_frame_equal(got, want)


@pytest.mark.unit
def test_slice_asof_tail_unsorted_index_fallback() -> None:
    idx = pd.to_datetime(["2024-01-03", "2024-01-01", "2024-01-02"], utc=True)
    df = pd.DataFrame({"x": [3, 1, 2]}, index=idx)
    ts = pd.Timestamp("2024-01-02", tz="UTC")
    got = _slice_asof_tail_reset_index(df, ts, 2)
    want = df[df.index <= ts].tail(2).reset_index()
    pd.testing.assert_frame_equal(got, want)
