from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.backtesting.backtest import (
    _filter_trade_records_by_window,
    _trade_metrics_for_standard_windows,
    compute_trade_metrics,
)


def test_compute_trade_metrics_empty_when_no_tp1() -> None:
    assert compute_trade_metrics(
        [
            {
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": True,
                "time_exit": False,
                "exit_reason": "SL",
            }
        ]
    ) == {}


def test_compute_trade_metrics_ratios() -> None:
    trades = [
        {
            "tp1_hit": True,
            "tp2_hit": True,
            "tp3_hit": True,
            "sl_hit": False,
            "time_exit": False,
            "exit_reason": "TP3",
        },
        {
            "tp1_hit": True,
            "tp2_hit": False,
            "tp3_hit": False,
            "sl_hit": False,
            "time_exit": True,
            "exit_reason": "mfe_drawdown_exceeded",
        },
        {
            "tp1_hit": True,
            "tp2_hit": True,
            "tp3_hit": False,
            "sl_hit": False,
            "time_exit": False,
            "exit_reason": "TP2_CLOSE",
        },
        {
            "tp1_hit": True,
            "tp2_hit": False,
            "tp3_hit": False,
            "sl_hit": True,
            "time_exit": False,
            "exit_reason": "SL",
        },
    ]
    m = compute_trade_metrics(trades)
    assert m["tp1_total"] == 4
    assert m["tp1_to_exit"]["count"] == 1
    assert m["tp1_to_exit"]["ratio"] == 0.25
    assert m["tp1_to_tp2"]["count"] == 2
    assert m["tp1_to_tp3"]["count"] == 1
    assert m["tp1_to_sl"]["count"] == 1
    assert m["exit_breakdown"]["mfe_exit"] == 1
    assert m["exit_breakdown"]["sl_exit"] == 1


def test_filter_and_windows() -> None:
    end = 1_000_000.0
    start = end - 40 * 86400.0
    recs = [
        {"close_ts": end - 5 * 86400, "tp1_hit": True, "tp2_hit": False, "tp3_hit": False, "sl_hit": False, "time_exit": True, "exit_reason": "x"},
        {"close_ts": end - 35 * 86400, "tp1_hit": True, "tp2_hit": True, "tp3_hit": False, "sl_hit": False, "time_exit": False, "exit_reason": "y"},
    ]
    last30 = _filter_trade_records_by_window(recs, end_ts=end, start_ts=start, window_days=30)
    assert len(last30) == 1
    w = _trade_metrics_for_standard_windows(recs, end_ts=end, start_ts=start, sim_days=90)
    assert "30" in w and "60" in w and "90" in w
    assert w["30"]["tp1_total"] == 1
    assert w["90"]["tp1_total"] == 2


def test_trade_metrics_includes_sim_days_key_for_short_run() -> None:
    """Shorter backtests must expose trade_metrics under str(sim_days), e.g. \"7\"."""
    end = 1_000_000.0
    start = end - 10 * 86400.0
    recs = [
        {
            "close_ts": end - 2 * 86400,
            "tp1_hit": True,
            "tp2_hit": False,
            "tp3_hit": False,
            "sl_hit": False,
            "time_exit": True,
            "exit_reason": "mfe_drawdown_exceeded",
        },
    ]
    w = _trade_metrics_for_standard_windows(recs, end_ts=end, start_ts=start, sim_days=7)
    assert w["30"] == {} and w["60"] == {} and w["90"] == {}
    assert "7" in w
    assert w["7"].get("tp1_total") == 1
