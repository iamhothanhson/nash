"""Trend-following pullback vs breakout attribution in backtest artifacts."""

from __future__ import annotations

from collections import Counter

from backtesting.backtest import (
    _build_family_attribution_payload,
    _trend_attribution_summary_lines,
    _trend_following_artifact_block,
    _trend_setup_metrics_block,
)


def test_trend_setup_metrics_block_roi_on_avg_margin():
    block = _trend_setup_metrics_block(
        trades=2,
        net_usdt=3.0,
        margin_usdt=20.0,
        initial_balance=100.0,
    )
    assert block["trades"] == 2
    assert block["avg_margin_usdt"] == 10.0
    assert block["net_profit_usdt"] == 3.0
    assert block["roi_percent"] == 30.0  # 3 / avg_margin(10) * 100


def test_build_family_attribution_separate_pullback_breakout_metrics():
    _, trend = _build_family_attribution_payload(
        family_counts={"liquidity": 0, "trend": 3},
        family_realized_pnl={"liquidity": 0.0, "trend": 9.0},
        family_margin_usdt={"liquidity": 0.0, "trend": 30.0},
        family_setup_breakdown={
            "liquidity": Counter(),
            "trend": Counter({"pullback": 2, "breakout": 1}),
        },
        initial_balance=100.0,
        trend_setup_realized_pnl={"pullback": 8.0, "breakout": 1.0},
        trend_setup_margin_usdt={"pullback": 20.0, "breakout": 10.0},
    )
    pb = trend["pullback_trades"]
    bo = trend["breakout_trades"]
    assert pb["trades"] == 2
    assert pb["net_profit_usdt"] == 8.0
    assert pb["margin_usdt"] == 20.0
    assert pb["roi_percent"] == 80.0  # 8 / avg_margin(10) * 100
    assert bo["trades"] == 1
    assert bo["net_profit_usdt"] == 1.0
    assert bo["margin_usdt"] == 10.0
    assert bo["roi_percent"] == 10.0  # 1 / avg_margin(10) * 100
    assert pb["roi_percent"] != bo["roi_percent"]


def test_trend_following_artifact_block_nested_shape():
    _, trend = _build_family_attribution_payload(
        family_counts={"liquidity": 0, "trend": 2},
        family_realized_pnl={"liquidity": 0.0, "trend": 5.0},
        family_margin_usdt={"liquidity": 0.0, "trend": 20.0},
        family_setup_breakdown={"liquidity": Counter(), "trend": Counter({"pullback": 1, "breakout": 1})},
        initial_balance=100.0,
        trend_setup_realized_pnl={"pullback": 4.0, "breakout": 1.0},
        trend_setup_margin_usdt={"pullback": 10.0, "breakout": 10.0},
    )
    block = _trend_following_artifact_block(trend, {"trend": 2}, {"trend": 25.0})
    assert block["trades"] == 2
    assert isinstance(block["pullback_trades"], dict)
    assert isinstance(block["breakout_trades"], dict)
    assert block["pullback_trades"]["net_profit_usdt"] == 4.0
    assert block["breakout_trades"]["net_profit_usdt"] == 1.0


def test_build_family_attribution_breakout_retest_metrics():
    _, trend = _build_family_attribution_payload(
        family_counts={"liquidity": 0, "trend": 11},
        family_realized_pnl={"liquidity": 0.0, "trend": 1.23},
        family_margin_usdt={"liquidity": 0.0, "trend": 25.74},
        family_setup_breakdown={
            "liquidity": Counter(),
            "trend": Counter({"breakout_retest": 11}),
        },
        initial_balance=100.0,
        trend_setup_realized_pnl={"pullback": 0.0, "breakout": 0.0, "breakout_retest": 1.23},
        trend_setup_margin_usdt={"pullback": 0.0, "breakout": 0.0, "breakout_retest": 25.74},
    )
    br = trend["breakout_retest_trades"]
    assert br["trades"] == 11
    assert br["avg_margin_usdt"] == 2.34
    assert br["roi_percent"] == 52.56  # 1.23 / avg_margin(2.34) * 100
    assert br["net_profit_usdt"] == 1.23


def test_trend_attribution_summary_lines_include_breakout_retest():
    _, trend = _build_family_attribution_payload(
        family_counts={"liquidity": 0, "trend": 11},
        family_realized_pnl={"liquidity": 0.0, "trend": 1.23},
        family_margin_usdt={"liquidity": 0.0, "trend": 25.74},
        family_setup_breakdown={
            "liquidity": Counter(),
            "trend": Counter({"breakout_retest": 11}),
        },
        initial_balance=100.0,
        trend_setup_realized_pnl={"pullback": 0.0, "breakout": 0.0, "breakout_retest": 1.23},
        trend_setup_margin_usdt={"pullback": 0.0, "breakout": 0.0, "breakout_retest": 25.74},
    )
    lines = _trend_attribution_summary_lines(trend)
    assert any("Trend Following: 11 trades:" in line for line in lines)
    assert any(
        "- Breakout Retest: 11 trades, Avg Margin: 2.34 USDT, ROI: +52.56%, Net Profit: +1.23 USDT"
        in line
        for line in lines
    )
