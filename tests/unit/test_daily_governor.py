"""Unit tests for ``strategy.market_regime.daily_governor``."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from order_planning.order_planner import DailyState
from portfolio.capital_tracker import VirtualAccount
from strategy.market_regime import daily_governor as dg

pytestmark = pytest.mark.unit


def test_rollover_returns_completed_utc_date(monkeypatch) -> None:
    class _FixedDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 5, 12, 0, 0, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(dg, "datetime", _FixedDateTime)
    state = DailyState()
    state.day_iso = "2026-05-11"
    v = VirtualAccount(1000.0)
    completed = dg.rollover_daily_if_needed(state, v)
    assert completed == "2026-05-11"
    assert state.day_iso == "2026-05-12"
    assert state.trades == 0


def test_rollover_first_run_returns_none(monkeypatch) -> None:
    class _FixedDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 5, 12, 0, 0, 5, tzinfo=timezone.utc)

    monkeypatch.setattr(dg, "datetime", _FixedDateTime)
    state = DailyState()
    v = VirtualAccount(1000.0)
    assert dg.rollover_daily_if_needed(state, v) is None
    assert state.day_iso == "2026-05-12"


def test_rollover_same_day_returns_none(monkeypatch) -> None:
    class _FixedDateTime:
        @staticmethod
        def now(tz=None):
            return datetime(2026, 5, 12, 12, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(dg, "datetime", _FixedDateTime)
    state = DailyState()
    state.day_iso = "2026-05-12"
    v = VirtualAccount(1000.0)
    assert dg.rollover_daily_if_needed(state, v) is None
