"""Unit tests for execution.risk_manager.calculate_position_plan."""

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

from app.config import settings
from app.execution.risk_manager import calculate_position_plan

pytestmark = pytest.mark.unit


def test_position_plan_caps_dollar_risk_after_notional_limits() -> None:
    """Wide SL + high notional cap: notional * sl must not exceed balance * max_execution_risk."""
    balance = 10_000.0
    risk_per_trade = 0.02
    sl_distance = 0.10
    max_exec = 0.01
    p = calculate_position_plan(
        balance=balance,
        risk_per_trade=risk_per_trade,
        sl_distance=sl_distance,
        entry_price=100.0,
        leverage=10.0,
        max_notional=50_000.0,
        max_notional_account_cap=None,
        max_execution_risk_per_trade=max_exec,
    )
    max_allowed = balance * max_exec
    assert p.notional * sl_distance <= max_allowed + 1e-6
    assert p.risk_amount == pytest.approx(p.notional * sl_distance, rel=1e-9)
    assert p.risk_amount <= max_allowed + 1e-6


def test_position_plan_respects_max_notional_after_risk_shrink() -> None:
    p = calculate_position_plan(
        balance=5000.0,
        risk_per_trade=0.05,
        sl_distance=0.02,
        entry_price=50.0,
        leverage=20.0,
        max_notional=800.0,
        max_notional_account_cap=None,
        max_execution_risk_per_trade=0.01,
    )
    assert p.notional <= 800.0 + 1e-6
    assert p.notional * 0.02 <= 5000.0 * 0.01 + 1e-6


def test_position_plan_does_not_bump_to_min_position_size_usdt(monkeypatch) -> None:
    monkeypatch.setattr(settings, "MIN_POSITION_SIZE_USDT", 20.0)
    p = calculate_position_plan(
        balance=30.0,
        risk_per_trade=0.01,
        sl_distance=0.02,
        entry_price=0.27,
        leverage=10.0,
        max_notional=500.0,
        max_notional_account_cap=500.0,
        max_execution_risk_per_trade=0.05,
        trade_symbol="FETUSDT",
    )
    assert p.notional == pytest.approx(15.0, rel=1e-9)
    assert p.notional < 20.0
