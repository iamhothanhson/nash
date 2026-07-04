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

from app.position_management.exit_bar_utils import (
    build_exit_bar_slice,
    decide_exit_from_bar_slice,
    replay_decide_exit,
    volume_ratio_asof,
)
from app.position_management.exit_manager import ExitManagerConfig, decide_exit


def _tiny_cfg() -> ExitManagerConfig:
    return ExitManagerConfig(
        min_hold_seconds=30.0,
        adx_threshold=20.0,
        min_volume_ratio=1.0,
        mfe_drawdown_threshold=0.35,
        mfe_drawdown_threshold_strong_trend=0.40,
        min_roi_mfe_drawdown_apply=0.0,
        long_hold_mfe_tighten_after_seconds=999999.0,
        long_hold_mfe_tighten_sub=0.0,
        mfe_tighten_step1_after_seconds=999999.0,
        mfe_tighten_step1_sub=0.0,
        mfe_tighten_step2_after_seconds=999999.0,
        mfe_tighten_step2_sub=0.0,
        mfe_profit_lock_after_seconds=999999.0,
        mfe_profit_lock_min_peak_roi=999999.0,
        mfe_profit_lock_min_roi=-999999.0,
        mfe_require_structure_break=True,
        mfe_immediate_on_threshold=False,
        min_hold_pre_tp1_seconds=2100.0,
        min_hold_after_tp1_seconds=900.0,
        ema_fast=9,
        ema_slow=21,
        min_consecutive_opposite_candles=2,
        min_momentum_weak_signals=2,
    )


@pytest.mark.unit
def test_volume_ratio_asof_tail20() -> None:
    rows = []
    base = pd.Timestamp("2024-01-01T00:00:00Z")
    for i in range(25):
        rows.append(
            {
                "timestamp": base + pd.Timedelta(minutes=5 * i),
                "open": 1.0,
                "high": 1.1,
                "low": 0.9,
                "close": 1.0,
                "volume": float(10 + i),
            }
        )
    df = pd.DataFrame(rows)
    asof = df[df["timestamp"] <= rows[-1]["timestamp"]]
    vr = volume_ratio_asof(asof)
    tail = asof.tail(20)
    expected = float(tail["volume"].iloc[-1]) / float(tail["volume"].mean())
    assert abs(vr - expected) < 1e-9


@pytest.mark.unit
def test_replay_decide_exit_matches_primary() -> None:
    base = pd.Timestamp("2024-06-01T12:00:00Z")
    rows5 = []
    rows15 = []
    for i in range(80):
        t = base + pd.Timedelta(minutes=5 * i)
        o = 100.0 + 0.01 * i
        rows5.append(
            {
                "timestamp": t,
                "open": o,
                "high": o + 0.5,
                "low": o - 0.5,
                "close": o + 0.1,
                "volume": 1000.0 + float(i),
            }
        )
    for j in range(30):
        t = base + pd.Timedelta(minutes=15 * j)
        o = 100.0 + 0.02 * j
        rows15.append(
            {
                "timestamp": t,
                "open": o,
                "high": o + 1.0,
                "low": o - 1.0,
                "close": o + 0.2,
                "volume": 3000.0,
            }
        )
    df5 = pd.DataFrame(rows5)
    df15 = pd.DataFrame(rows15)
    bar_open = rows5[50]["timestamp"]
    sl = build_exit_bar_slice(df5=df5, df15=df15, bar_open=bar_open)
    assert sl is not None
    cfg = _tiny_cfg()
    kwargs = dict(
        time_in_trade=4000.0,
        current_roi=0.05,
        roi_history=[{"t": 1.0, "roi": 0.05}, {"t": 4000.0, "roi": 0.05}],
        max_roi_seen=0.2,
        exit_manager=cfg,
        direction="LONG",
        time_since_tp1=None,
        symbol="TESTUSDT",
        decide_exit_fn=decide_exit,
    )
    a = decide_exit_from_bar_slice(slice_=sl, **kwargs)
    b = replay_decide_exit(df5=df5, df15=df15, bar_open=pd.Timestamp(bar_open), **kwargs)
    assert a.get("action") == b.get("action")
    assert a.get("reason") == b.get("reason")
