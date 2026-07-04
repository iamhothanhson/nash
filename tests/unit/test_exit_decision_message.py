from __future__ import annotations

import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.monitoring.messages import (
    format_exit_decision_close_line,
    format_time_exit_reason_with_thresholds,
)


@pytest.mark.unit
def test_format_exit_decision_close_line_mfe_includes_roi_drop_percent() -> None:
    line = format_exit_decision_close_line(
        "TAOUSDT",
        "mfe_drawdown_exceeded",
        metrics={"mfe_drawdown_normalized": 0.6},
        current_roi=4.0,
        max_roi_seen=10.0,
    )
    assert "[EXIT DECISION] TAOUSDT | Action: CLOSE | Reason: mfe_drawdown_exceeded" in line
    assert "ROI Drop Percent: 6.00%" in line


@pytest.mark.unit
def test_format_exit_decision_close_line_other_reason_omits_roi_drop() -> None:
    line = format_exit_decision_close_line(
        "TAOUSDT",
        "conditions_not_met",
        metrics={"mfe_drawdown_normalized": 0.6},
    )
    assert "ROI Drop Percent" not in line


@pytest.mark.unit
def test_format_time_exit_reason_with_thresholds_mfe() -> None:
    cfg = SimpleNamespace(
        min_roi_mfe_drawdown_apply=7.0,
        mfe_drawdown_threshold=0.3,
        mfe_drawdown_threshold_strong_trend=0.35,
    )
    detail = format_time_exit_reason_with_thresholds(
        "mfe_drawdown_exceeded",
        exit_manager=cfg,
        metrics={"strong_trend": True},
    )
    assert detail == (
        "mfe_drawdown_exceeded | peak ROI >= 7.00% and ROI giveback >= 35.00%"
    )
