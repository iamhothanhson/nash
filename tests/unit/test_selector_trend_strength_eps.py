from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.strategy_selector.models import TrendRegimeComponents, TrendRegimeReport
from app.strategy_selector.selector import StrategySelector


def _regime(strength: float) -> TrendRegimeReport:
    z = TrendRegimeComponents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    return TrendRegimeReport(
        allows_trend_strategy=True,
        trend_strength=strength,
        primary_reason="qualified",
        components=z,
        metadata={},
    )


@pytest.mark.unit
def test_trend_strength_eps_allows_borderline_score(monkeypatch) -> None:
    monkeypatch.setattr("app.strategy_selector.selector.SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE", 0.35)
    monkeypatch.setattr("app.strategy_selector.selector.SELECTOR_TREND_MIN_STRENGTH_EPS", 0.001)
    monkeypatch.setattr("app.strategy_selector.selector.TREND_REQUIRE_REGIME_DIRECTION_MATCH", False)

    sel = StrategySelector(regime_detector=MagicMock())
    ok, blocked = sel._should_include_trend(
        trend_signal=SimpleNamespace(direction="LONG"),
        regime=_regime(0.3493),
        enable_trend=True,
        trend_regime_filter=False,
    )
    assert ok is True
    assert blocked is None


@pytest.mark.unit
def test_trend_strength_eps_zero_keeps_strict_gate(monkeypatch) -> None:
    monkeypatch.setattr("app.strategy_selector.selector.SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE", 0.35)
    monkeypatch.setattr("app.strategy_selector.selector.SELECTOR_TREND_MIN_STRENGTH_EPS", 0.0)
    monkeypatch.setattr("app.strategy_selector.selector.TREND_REQUIRE_REGIME_DIRECTION_MATCH", False)

    sel = StrategySelector(regime_detector=MagicMock())
    ok, blocked = sel._should_include_trend(
        trend_signal=SimpleNamespace(direction="LONG"),
        regime=_regime(0.3493),
        enable_trend=True,
        trend_regime_filter=False,
    )
    assert ok is False
    assert blocked is not None
    assert blocked["status"] == "blocked_by_trend_strength"
