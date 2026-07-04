from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.backtesting.backtest import (
    _aggregate_exit_metrics_for_pairs,
    _build_exit_metrics_artifact_payload,
    _zip_trade_path_pairs,
)

pytestmark = pytest.mark.unit


def test_aggregate_exit_metrics_time_exit_subreasons_and_unspecified() -> None:
    pairs = [
        (
            1.0,
            {
                "close_ts": 100.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": True,
                "exit_reason": "mfe_drawdown_exceeded",
            },
        ),
        (
            -0.5,
            {
                "close_ts": 200.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": True,
                "exit_reason": "TIME EXIT",
            },
        ),
    ]
    out = _aggregate_exit_metrics_for_pairs(pairs)
    assert out["total_trades"] == 2
    te = out["time_exit"]
    assert te["total_count"] == 2
    assert te["mfe_drawdown_exceeded"]["total_count"] == 1
    assert te["mfe_drawdown_exceeded"]["win"] == 1
    assert te["unspecified"]["total_count"] == 1
    assert te["unspecified"]["loss"] == 1
    assert te["entry_time_exit"]["total_count"] == 0
    assert te["tp1_time_exit"]["total_count"] == 2
    assert te["tp2_time_exit"]["total_count"] == 0
    assert "tp3_time_exit" not in te


def test_aggregate_exit_metrics_tp_time_exit_partition_by_deepest_tp() -> None:
    pairs = [
        (
            0.1,
            {
                "close_ts": 1.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": True,
                "exit_reason": "mfe_drawdown_exceeded",
            },
        ),
        (
            0.2,
            {
                "close_ts": 2.0,
                "tp1_hit": True,
                "tp2_hit": True,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": True,
                "exit_reason": "mfe_drawdown_exceeded",
            },
        ),
        (
            0.3,
            {
                "close_ts": 3.0,
                "tp1_hit": True,
                "tp2_hit": True,
                "tp3_hit": True,
                "sl_hit": False,
                "time_exit": True,
                "exit_reason": "mfe_drawdown_exceeded",
            },
        ),
    ]
    te = _aggregate_exit_metrics_for_pairs(pairs)["time_exit"]
    assert te["total_count"] == 3
    assert te["tp1_time_exit"]["total_count"] == 1
    assert te["tp2_time_exit"]["total_count"] == 2
    assert "tp3_time_exit" not in te
    pairs = [
        (
            -2.0,
            {
                "close_ts": 1.0,
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": True,
                "time_exit": False,
                "exit_reason": "SL",
            },
        ),
        (
            -1.0,
            {
                "close_ts": 2.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": True,
                "time_exit": False,
                "exit_reason": "SL",
            },
        ),
        (
            3.0,
            {
                "close_ts": 3.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": False,
                "exit_reason": "TP1_CLOSE",
            },
        ),
    ]
    out = _aggregate_exit_metrics_for_pairs(pairs)
    assert out["stop_loss"]["SL"]["total_count"] == 1
    assert out["stop_loss"]["SL"]["loss"] == 1
    assert "TP1_SL" not in out["stop_loss"]
    assert "TP2_SL" not in out["stop_loss"]
    tp = out["target_profit"]
    assert tp["Stop_At_TP1"]["total_count"] == 2
    assert tp["Stop_At_TP1"]["win"] == 1
    assert tp["Stop_At_TP1"]["loss"] == 1
    assert tp["Stop_At_TP2"]["total_count"] == 0
    assert tp["Stop_At_TP3"]["total_count"] == 0


def test_stop_loss_sl_excludes_post_tp1_breakeven_stops() -> None:
    pairs = [
        (
            -1.0,
            {
                "close_ts": 1.0,
                "tp1_hit": False,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": True,
                "time_exit": False,
                "exit_reason": "SL",
            },
        ),
        (
            0.5,
            {
                "close_ts": 2.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": True,
                "time_exit": False,
                "exit_reason": "SL",
            },
        ),
    ]
    out = _aggregate_exit_metrics_for_pairs(pairs)
    assert out["stop_loss"]["SL"]["total_count"] == 1
    assert out["target_profit"]["Stop_At_TP1"]["total_count"] == 1
    assert (
        out["stop_loss"]["SL"]["total_count"]
        + out["target_profit"]["Stop_At_TP1"]["total_count"]
        + out["target_profit"]["Stop_At_TP2"]["total_count"]
        + out["target_profit"]["Stop_At_TP3"]["total_count"]
        == out["total_trades"]
    )


def test_aggregate_exit_metrics_target_profit_by_deepest_tp_hit() -> None:
    pairs = [
        (
            2.0,
            {
                "close_ts": 1.0,
                "tp1_hit": True,
                "tp2_hit": True,
                "tp3_hit": False,
                "sl_hit": True,
                "time_exit": False,
                "exit_reason": "SL",
            },
        ),
        (
            1.0,
            {
                "close_ts": 2.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": True,
                "exit_reason": "mfe_drawdown_exceeded",
            },
        ),
    ]
    tp = _aggregate_exit_metrics_for_pairs(pairs)["target_profit"]
    assert tp["Stop_At_TP2"]["total_count"] == 1
    assert tp["Stop_At_TP2"]["win"] == 1
    assert tp["Stop_At_TP1"]["total_count"] == 1
    assert tp["Stop_At_TP1"]["win"] == 1
    assert tp["Stop_At_TP3"]["total_count"] == 0


def test_zip_trade_path_pairs_requires_trades_list_on_result() -> None:
    records = [
        {
            "close_ts": 100.0,
            "tp1_hit": True,
            "tp2_hit": False,
            "tp3_hit": False,
            "sl_hit": True,
            "time_exit": False,
            "exit_reason": "SL",
            "realized_pnl": -1.0,
        }
    ]
    pairs_fb = _zip_trade_path_pairs({"trade_path_records": records})
    assert len(pairs_fb) == 1 and pairs_fb[0][0] == -1.0
    pairs = _zip_trade_path_pairs({"trades": [-1.0], "trade_path_records": records})
    assert len(pairs) == 1
    assert pairs[0][0] == -1.0


def test_build_exit_metrics_payload_respects_window() -> None:
    end = 10.0 * 86400.0
    start = 0.0
    pairs = []
    for i in range(5):
        ts = (4.0 + float(i) * 0.5) * 86400.0
        pairs.append(
            (
                0.1,
                {
                    "close_ts": ts,
                    "tp1_hit": False,
                    "tp2_hit": False,
                    "tp3_hit": False,
                    "sl_hit": False,
                    "time_exit": True,
                    "exit_reason": "mfe_drawdown_exceeded",
                },
            )
        )
    result = {
        "trades": [p[0] for p in pairs],
        "trade_path_records": [p[1] for p in pairs],
        "simulation_end_ts": end,
        "simulation_start_ts": start,
    }
    payload = _build_exit_metrics_artifact_payload(result, sim_days=7)
    assert payload["7"]["total_trades"] == 5
    assert payload["7"]["time_exit"]["mfe_drawdown_exceeded"]["total_count"] == 5
    assert payload["7"]["time_exit"]["entry_time_exit"]["total_count"] == 5
    assert payload["7"]["time_exit"]["tp1_time_exit"]["total_count"] == 0
    assert payload["7"]["time_exit"]["tp2_time_exit"]["total_count"] == 0
    assert "tp3_time_exit" not in payload["7"]["time_exit"]
    assert set(payload.keys()) == {"7"}


def test_build_exit_metrics_payload_single_key_matches_run_days() -> None:
    end = 60.0 * 86400.0
    start = 0.0
    pairs = [
        (
            1.0,
            {
                "close_ts": 59.0 * 86400.0,
                "tp1_hit": True,
                "tp2_hit": False,
                "tp3_hit": False,
                "sl_hit": False,
                "time_exit": False,
                "exit_reason": "TP1",
            },
        ),
    ]
    result = {
        "trades": [p[0] for p in pairs],
        "trade_path_records": [p[1] for p in pairs],
        "simulation_end_ts": end,
        "simulation_start_ts": start,
    }
    payload = _build_exit_metrics_artifact_payload(result, sim_days=60)
    assert set(payload.keys()) == {"60"}
    assert payload["60"]["total_trades"] == 1
