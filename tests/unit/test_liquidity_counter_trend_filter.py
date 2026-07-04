"""Liquidity sweep should not fade clear 1H trend bias."""

from __future__ import annotations

import pandas as pd

from strategy.liquidity_sweep_reversal import sweep_revesal_config as liq_cfg
from strategy.liquidity_sweep_reversal.base_sweep_revesal import LiquiditySweepReversalBase


def _close_frame(values: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": values,
            "high": [v + 1.0 for v in values],
            "low": [v - 1.0 for v in values],
            "close": values,
            "volume": [1000.0] * len(values),
        }
    )


def test_liquidity_short_blocked_when_1h_bias_up(monkeypatch):
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_AVOID_COUNTER_TREND_ENABLED", True, raising=False)
    strat = LiquiditySweepReversalBase()
    data_1h = _close_frame([100.0 + float(i) for i in range(80)])

    assert strat._htf_trend_bias(data_1h) == "UP"
    assert strat._filter_counter_trend_liquidity_directions(
        ["LONG", "SHORT"], data_1h, symbol="TAOUSDT"
    ) == ["LONG"]


def test_liquidity_long_blocked_when_1h_bias_down(monkeypatch):
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_AVOID_COUNTER_TREND_ENABLED", True, raising=False)
    strat = LiquiditySweepReversalBase()
    data_1h = _close_frame([200.0 - float(i) for i in range(80)])

    assert strat._htf_trend_bias(data_1h) == "DOWN"
    assert strat._filter_counter_trend_liquidity_directions(
        ["LONG", "SHORT"], data_1h, symbol="TAOUSDT"
    ) == ["SHORT"]


def test_liquidity_allows_both_when_1h_bias_neutral(monkeypatch):
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_AVOID_COUNTER_TREND_ENABLED", True, raising=False)
    strat = LiquiditySweepReversalBase()
    data_1h = _close_frame([100.0 + (0.1 if i % 2 else 0.0) for i in range(80)])

    assert strat._htf_trend_bias(data_1h) == "NEUTRAL"
    assert strat._filter_counter_trend_liquidity_directions(
        ["LONG", "SHORT"], data_1h, symbol="TAOUSDT"
    ) == ["LONG", "SHORT"]


def test_liquidity_counter_trend_filter_can_be_disabled(monkeypatch):
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_AVOID_COUNTER_TREND_ENABLED", False, raising=False)
    strat = LiquiditySweepReversalBase()
    data_1h = _close_frame([100.0 + float(i) for i in range(80)])

    assert strat._filter_counter_trend_liquidity_directions(
        ["LONG", "SHORT"], data_1h, symbol="TAOUSDT"
    ) == ["LONG", "SHORT"]

