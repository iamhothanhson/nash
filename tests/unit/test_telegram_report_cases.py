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

from monitoring.telegram_test_suite import (
    REPORT_CASE_KEYS,
    all_report_test_cases,
    sample_month_cumulative_snapshot,
    sample_performance_snapshot,
)

pytestmark = pytest.mark.unit


def test_report_case_keys() -> None:
    keys = {c.key for c in all_report_test_cases()}
    assert keys == set(REPORT_CASE_KEYS)
    assert "monthly_cumulative" in keys


def test_sample_performance_snapshot_has_export_keys() -> None:
    snap = sample_performance_snapshot()
    assert snap["daily_pnl"] == 6.92
    assert snap["total_trade"] == 3
    assert "trades" not in snap
