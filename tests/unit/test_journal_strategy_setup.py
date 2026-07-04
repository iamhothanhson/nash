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

from app.monitoring.position_journal import journal_strategy_setup_value


@pytest.mark.unit
def test_journal_strategy_setup_liquidity_default() -> None:
    assert journal_strategy_setup_value() == "liquidity_sweep_reversal"
    assert journal_strategy_setup_value(strategy_family="liquidity", setup_type="liquidity_sweep") == (
        "liquidity_sweep_reversal"
    )


@pytest.mark.unit
def test_journal_strategy_setup_trend_breakout_pullback() -> None:
    assert journal_strategy_setup_value(strategy_family="trend_following", setup_type="breakout") == (
        "trend_following_breakout"
    )
    assert journal_strategy_setup_value(strategy_family="trend", setup_type="pullback") == (
        "trend_following_pullback"
    )


@pytest.mark.unit
def test_journal_strategy_setup_explicit_override() -> None:
    assert journal_strategy_setup_value(strategy_setup="custom_tag") == "custom_tag"
