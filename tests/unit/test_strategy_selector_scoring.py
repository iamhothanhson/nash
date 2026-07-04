"""Unit tests for strategy selector scoring helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from strategy_selector.models import StrategyCandidate, TrendRegimeComponents, TrendRegimeReport
from strategy_selector.scoring import expected_reward_risk, score_candidate


def test_expected_reward_risk_bounded():
    c = StrategyCandidate(
        strategy_family="liquidity",
        setup_type="liquidity_sweep",
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        take_profit=103.0,
        r_multiple=0.01,
        confidence=0.8,
        timestamp=pd.Timestamp.utcnow().to_pydatetime(),
        native_signal=None,
    )
    assert 0.0 <= expected_reward_risk(c) <= 1.0


def test_score_candidate_composite_positive():
    regime = TrendRegimeReport(
        allows_trend_strategy=True,
        trend_strength=0.7,
        primary_reason="qualified",
        components=TrendRegimeComponents(0.5, 0.5, 0.5, 0.5, 0.5, 0.5),
    )
    c = StrategyCandidate(
        strategy_family="liquidity",
        setup_type="liquidity_sweep",
        direction="LONG",
        entry=100.0,
        stop_loss=99.0,
        take_profit=103.0,
        r_multiple=0.01,
        confidence=0.85,
        timestamp=pd.Timestamp.utcnow().to_pydatetime(),
        native_signal=None,
        metadata={"volatility": 0.005},
    )
    bd = score_candidate(c, family="liquidity", regime=regime, data_15m=None, data_5m=None)
    assert bd.composite > 0.0
    assert bd.expected_edge > 0.0
