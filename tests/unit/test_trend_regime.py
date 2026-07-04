"""Tests for trend regime (re-exported from strategy_selector)."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from strategy.market_regime.trend_regime_detector import TrendRegimeDetector


def test_trend_regime_empty_or_short_returns_false():
    det = TrendRegimeDetector()
    empty = det.evaluate(pd.DataFrame())
    assert empty.allows_trend_strategy is False
    assert empty.primary_reason == "insufficient_bars_1h"

    df = pd.DataFrame(
        {"high": [1.0, 1.1], "low": [0.9, 1.0], "close": [1.0, 1.05]}
    )
    short = det.evaluate(df)
    assert short.allows_trend_strategy is False
    assert short.primary_reason == "insufficient_bars_1h"
