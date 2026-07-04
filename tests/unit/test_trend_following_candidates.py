"""Trend-following SetupCandidate integrity and arbitration (isolated from reversal)."""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from config import settings
from strategy.trend_following import trend_following_config as tf_cfg
from strategy.trend_following.base_trend_following import (
    SETUP_PRIORITY,
    SetupCandidate,
    TrendFollowingStrategyBase,
)


def _dummy_ohlcv(rows: int = 60) -> pd.DataFrame:
    base = list(range(rows))
    return pd.DataFrame(
        {
            "open": [float(x) + 100 for x in base],
            "high": [float(x) + 101 for x in base],
            "low": [float(x) + 99 for x in base],
            "close": [float(x) + 100.5 for x in base],
            "volume": [1000.0 + float(x) for x in base],
        }
    )


def _pullback_short_frame(rows: int = 60) -> pd.DataFrame:
    close = [100.0] * (rows - 2) + [100.2, 99.8]
    open_ = close.copy()
    open_[-1] = 100.1
    high = [v + 0.4 for v in close]
    low = [v - 0.4 for v in close]
    low[-1] = min(low[-2], close[-1] - 0.5)
    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * rows,
        }
    )


def test_setup_candidate_keyword_preserves_debug_reason_and_numeric_confidence():
    c = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=248.25,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=14.0,
        trigger_type="breakout_long",
        confidence=0.0,
        debug_reason="breakout_strength=0.002000,vol_ratio=1.050",
    )
    assert isinstance(c.confidence, float)
    assert c.confidence == 0.0
    assert isinstance(c.raw_score, float)
    assert c.trigger_type == "breakout_long"
    assert "breakout_strength" in (c.debug_reason or "")


@patch("strategy.trend_following.pullback.calculate_rsi")
@patch("strategy.trend_following.pullback.calculate_ema")
def test_pullback_long_rejected_without_prior_impulse(mock_ema, mock_rsi):
    n = 60
    # Flat window: no +3% move from bar -12 to bar -4.
    close_vals = [100.0] * n
    close_vals[-4] = 100.5
    close_vals[-1] = 100.6
    close = pd.Series(close_vals)
    open_ = close - 0.1
    high = close + 0.5
    low = close - 0.5
    ema20 = pd.Series([99.5] * n)
    ema50 = pd.Series([99.0] * n)
    mock_ema.side_effect = [ema20, ema50]
    mock_rsi.return_value = pd.Series([55.0] * n)

    df = pd.DataFrame(
        {
            "open": open_.tolist(),
            "high": high.tolist(),
            "low": low.tolist(),
            "close": close.tolist(),
            "volume": [1000.0] * n,
        }
    )
    df.iloc[-1, df.columns.get_loc("open")] = float(df.iloc[-1]["close"]) - 0.2
    df.iloc[-1, df.columns.get_loc("close")] = float(df.iloc[-1]["open"]) + 0.4
    df.iloc[-1, df.columns.get_loc("high")] = float(df.iloc[-1]["close"]) + 0.1
    df.iloc[-2, df.columns.get_loc("high")] = float(df.iloc[-2]["close"]) - 0.1

    strat = TrendFollowingStrategyBase()
    out = strat.pullback_long_candidate(df)
    assert out is None


@patch("strategy.trend_following.pullback.calculate_rsi")
@patch("strategy.trend_following.pullback.calculate_ema")
def test_pullback_short_rejected_when_15m_ema_stack_is_bullish(mock_ema, mock_rsi):
    n = 60
    # EMA20 has a short-term negative slope, but still sits above EMA50.
    ema20 = pd.Series([100.0] * (n - 5) + [100.3, 100.2, 100.1, 100.0, 99.9])
    ema50 = pd.Series([99.0] * n)
    mock_ema.side_effect = [ema20, ema50]
    mock_rsi.return_value = pd.Series([40.0] * n)

    strat = TrendFollowingStrategyBase()
    out = strat.pullback_short_candidate(_pullback_short_frame(n))

    assert out is None


@patch("strategy.trend_following.breakout_retest.detector.calculate_rsi")
@patch("strategy.trend_following.breakout_retest.detector.calculate_ema")
def test_breakout_retest_long_candidate(mock_ema, mock_rsi):
    n = 60
    close = [100.0] * n
    open_ = [99.95] * n
    high = [100.0] * n
    low = [99.8] * n
    close[-3] = 100.45
    close[-2] = 100.55
    open_[-1] = 100.1
    close[-1] = 100.45
    high[-1] = 100.5
    low[-1] = 100.0
    df = pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": [1000.0] * (n - 1) + [1600.0],
        }
    )
    ema20 = pd.Series([100.0 + float(i) * 0.01 for i in range(n)])
    ema50 = pd.Series([99.0 + float(i) * 0.005 for i in range(n)])
    mock_ema.side_effect = [ema20, ema50]
    mock_rsi.return_value = pd.Series([60.0] * n)

    strat = TrendFollowingStrategyBase()
    out = strat.breakout_retest_long_candidate(df)

    assert out is not None
    assert out.setup_type == "breakout_retest"
    assert out.trigger_type == "breakout_retest_long"


def test_score_candidate_coerces_non_numeric_confidence():
    """Strings like setup labels must never stick in confidence; coerce to 0.0."""
    strat = TrendFollowingStrategyBase()
    bad = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=100.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=11.0,
        trigger_type="breakout_long",
        confidence="breakout",  # type: ignore[arg-type]
        debug_reason="test",
    )
    df = _dummy_ohlcv()
    with patch.object(strat, "_plan_debug_enabled", return_value=True):
        with patch("strategy.trend_following.base_trend_following.file_log"):
            out = strat._score_candidate(bad, df, volatility=0.01, symbol="TAOUSDT")
    assert isinstance(out.confidence, float)
    assert out.confidence == out.confidence  # not NaN
    assert 0.0 <= out.confidence <= 1.0


def test_score_candidate_raises_on_invalid_raw_score_type():
    strat = TrendFollowingStrategyBase()
    bad = SetupCandidate(
        setup_type="pullback",
        direction="SHORT",
        anchor=100.0,
        setup_points=3,
        key_level_points=2,
        confirmation_points=2,
        raw_score="bad",  # type: ignore[arg-type]
        trigger_type="pullback_short",
        confidence=0.0,
        debug_reason="test",
    )
    df = _dummy_ohlcv()
    with patch.object(strat, "_plan_debug_enabled", return_value=True):
        with patch("strategy.trend_following.base_trend_following.file_log"):
            with pytest.raises(TypeError, match="Invalid candidate raw_score type"):
                strat._score_candidate(bad, df, volatility=0.01, symbol="TAOUSDT")


def test_score_candidate_raises_on_invalid_trigger_type():
    strat = TrendFollowingStrategyBase()
    bad = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=100.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=11.0,
        trigger_type="",  # invalid
        confidence=0.0,
        debug_reason="test",
    )
    df = _dummy_ohlcv()
    with patch.object(strat, "_plan_debug_enabled", return_value=True):
        with patch("strategy.trend_following.base_trend_following.file_log"):
            with pytest.raises(TypeError, match="Invalid candidate trigger_type"):
                strat._score_candidate(bad, df, volatility=0.01, symbol="TAOUSDT")


@patch("strategy.trend_following.base_trend_following.calculate_rsi")
@patch("strategy.trend_following.base_trend_following.calculate_atr")
@patch("strategy.trend_following.base_trend_following.calculate_ema")
def test_score_candidate_returns_numeric_confidence(mock_ema, mock_atr, mock_rsi):
    n = 60
    mock_ema.return_value = pd.Series([100.0 + float(i) * 0.01 for i in range(n)])
    mock_atr.return_value = pd.Series([2.0] * n)
    mock_rsi.return_value = pd.Series([55.0] * n)
    strat = TrendFollowingStrategyBase()
    good = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=100.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=14.0,
        trigger_type="breakout_long",
        confidence=0.0,
        debug_reason="seed",
    )
    out = strat._score_candidate(good, _dummy_ohlcv(n), volatility=0.02, symbol="TAOUSDT")
    assert isinstance(out.confidence, float)
    assert isinstance(out.raw_score, float)
    assert 0.0 <= out.confidence <= 1.0


def test_select_best_candidate_prefers_pullback_at_equal_primary_scores(monkeypatch):
    monkeypatch.setattr(tf_cfg, "TREND_PULLBACK_SELECT_MARGIN", 1.5, raising=False)
    strat = TrendFollowingStrategyBase()
    pullback = SetupCandidate(
        setup_type="pullback",
        direction="LONG",
        anchor=100.0,
        setup_points=3,
        key_level_points=3,
        confirmation_points=3,
        raw_score=16.0,
        trigger_type="pullback_long",
        confidence=0.8,
        debug_reason="p",
    )
    breakout = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=101.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=17.0,
        trigger_type="breakout_long",
        confidence=0.8,
        debug_reason="b",
    )
    assert SETUP_PRIORITY["breakout"] > SETUP_PRIORITY["pullback"]
    with patch.object(strat, "_plan_debug_enabled", return_value=False):
        best = strat._select_best_candidate("TAOUSDT", [pullback, breakout])
    assert best is not None
    assert best.setup_type == "pullback"


def test_select_best_candidate_keeps_clear_breakout_winner(monkeypatch):
    monkeypatch.setattr(tf_cfg, "TREND_PULLBACK_SELECT_MARGIN", 1.5, raising=False)
    strat = TrendFollowingStrategyBase()
    pullback = SetupCandidate(
        setup_type="pullback",
        direction="LONG",
        anchor=100.0,
        setup_points=3,
        key_level_points=3,
        confirmation_points=3,
        raw_score=13.0,
        trigger_type="pullback_long",
        confidence=0.8,
        debug_reason="p",
    )
    breakout = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=101.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=17.0,
        trigger_type="breakout_long",
        confidence=0.8,
        debug_reason="b",
    )
    with patch.object(strat, "_plan_debug_enabled", return_value=False):
        best = strat._select_best_candidate("TAOUSDT", [pullback, breakout])
    assert best is not None
    assert best.setup_type == "breakout"


def test_select_best_candidate_stable_order_same_trigger_types():
    strat = TrendFollowingStrategyBase()
    a = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=100.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=12.0,
        trigger_type="breakout_long",
        confidence=0.7,
        debug_reason="a",
    )
    b = SetupCandidate(
        setup_type="breakout",
        direction="SHORT",
        anchor=99.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=12.0,
        trigger_type="breakout_short",
        confidence=0.7,
        debug_reason="b",
    )
    with patch.object(strat, "_plan_debug_enabled", return_value=False):
        best1 = strat._select_best_candidate("X", [a, b])
        best2 = strat._select_best_candidate("X", [b, a])
    assert best1.trigger_type == best2.trigger_type


def test_auction_log_breakout_raw_score_lead(monkeypatch):
    monkeypatch.setattr(tf_cfg, "TREND_PULLBACK_SELECT_MARGIN", 1.5, raising=False)
    strat = TrendFollowingStrategyBase()
    pullback = SetupCandidate(
        setup_type="pullback",
        direction="LONG",
        anchor=100.0,
        setup_points=3,
        key_level_points=3,
        confirmation_points=3,
        raw_score=13.0,
        trigger_type="pullback_long",
        confidence=0.8,
        debug_reason="p",
    )
    breakout = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=101.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=17.0,
        trigger_type="breakout_long",
        confidence=0.8,
        debug_reason="b",
    )
    with patch.object(strat, "_plan_debug_enabled", return_value=False):
        with patch.object(strat, "_auction_log_enabled", return_value=True):
            with patch("strategy.trend_following.base_trend_following.file_log") as fl:
                best = strat._select_best_candidate("TAOUSDT", [pullback, breakout])
                assert best.setup_type == "breakout"
                auction_lines = [c.args[0] for c in fl.call_args_list if "[TREND_AUCTION]" in c.args[0]]
                assert len(auction_lines) == 1
            assert "reason=breakout_raw_score_lead" in auction_lines[0]
            assert "pullback_would_override=false" in auction_lines[0]


def test_auction_log_pullback_bias_override(monkeypatch):
    monkeypatch.setattr(tf_cfg, "TREND_PULLBACK_SELECT_MARGIN", 1.5, raising=False)
    strat = TrendFollowingStrategyBase()
    pullback = SetupCandidate(
        setup_type="pullback",
        direction="LONG",
        anchor=100.0,
        setup_points=3,
        key_level_points=3,
        confirmation_points=3,
        raw_score=15.0,
        trigger_type="pullback_long",
        confidence=0.8,
        debug_reason="p",
    )
    breakout = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=101.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=15.0,
        trigger_type="breakout_long",
        confidence=0.8,
        debug_reason="b",
    )
    with patch.object(strat, "_plan_debug_enabled", return_value=False):
        with patch.object(strat, "_auction_log_enabled", return_value=True):
            with patch("strategy.trend_following.base_trend_following.file_log") as fl:
                best = strat._select_best_candidate("TAOUSDT", [pullback, breakout])
                assert best.setup_type == "pullback"
                auction_lines = [c.args[0] for c in fl.call_args_list if "[TREND_AUCTION]" in c.args[0]]
                assert len(auction_lines) == 1
            assert "reason=pullback_bias_override" in auction_lines[0]
            assert "pullback_would_override=true" in auction_lines[0]
            assert "pre_override=breakout_long" in auction_lines[0]


def test_auction_log_disabled_without_flags(monkeypatch):
    monkeypatch.setattr(settings, "TREND_SETUP_AUCTION_LOG", False)
    strat = TrendFollowingStrategyBase()
    pullback = SetupCandidate(
        setup_type="pullback",
        direction="LONG",
        anchor=100.0,
        setup_points=3,
        key_level_points=3,
        confirmation_points=3,
        raw_score=13.0,
        trigger_type="pullback_long",
        confidence=0.8,
        debug_reason="p",
    )
    breakout = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=101.0,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=15.0,
        trigger_type="breakout_long",
        confidence=0.8,
        debug_reason="b",
    )
    with patch.object(strat, "_plan_debug_enabled", return_value=False):
        with patch("strategy.trend_following.base_trend_following.file_log") as fl:
            strat._select_best_candidate("TAOUSDT", [pullback, breakout])
            assert not any("[TREND_AUCTION]" in (c.args[0] if c.args else "") for c in fl.call_args_list)


def test_log_candidate_does_not_crash():
    strat = TrendFollowingStrategyBase()
    c = SetupCandidate(
        setup_type="breakout",
        direction="LONG",
        anchor=248.31,
        setup_points=5,
        key_level_points=3,
        confirmation_points=3,
        raw_score=17.2,
        trigger_type="breakout_long",
        confidence=0.91,
        debug_reason="ok",
    )
    with patch.object(strat, "_plan_debug_enabled", return_value=True):
        with patch("strategy.trend_following.base_trend_following.file_log") as fl:
            strat._log_candidate("TAOUSDT", c)
            assert fl.called
