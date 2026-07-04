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

from app.monitoring.telegram_test_suite import all_telegram_test_cases, run_telegram_test_suite


@pytest.mark.unit
def test_all_telegram_test_cases_has_expected_keys() -> None:
    keys = {c.key for c in all_telegram_test_cases()}
    assert "order_plan_rejected_exposure" in keys
    assert "risk_limit" in keys
    assert "exchange_entry_blocked" in keys
    assert "lifecycle_open" in keys
    assert len(keys) >= 12


@pytest.mark.unit
def test_run_telegram_test_suite_dry_run(monkeypatch) -> None:
    from app.config import settings

    monkeypatch.setattr(settings, "ALERTS_MODES", ("demo", "live"), raising=False)
    rows = run_telegram_test_suite(modes=("demo",), dry_run=True, only=("risk_limit",))
    assert len(rows) == 1
    assert rows[0]["key"] == "risk_limit"
    assert rows[0]["skipped"] == "dry-run"
