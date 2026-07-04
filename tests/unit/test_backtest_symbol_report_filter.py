"""Portfolio run with --symbol report filter uses per-symbol attribution."""

from __future__ import annotations

from collections import Counter

import json

from backtesting.backtest import (
    _apply_symbol_attribution_slice,
    _backtest_symbol_day_window_payload,
    _filter_result_for_report,
    _resolve_backtest_run_symbols,
    _update_backtest_symbol_artifact,
    format_backtest_report,
)


def _portfolio_result() -> dict:
    return {
        "days": 7,
        "symbol": "TAO,RENDER",
        "initial_balance": 100.0,
        "final_balance": 120.0,
        "net_profit": 20.0,
        "total_trades": 50,
        "trades_per_day": 50 / 7.0,
        "win_rate": 0.6,
        "profit_factor": 1.5,
        "max_drawdown": 0.05,
        "roi": 20.0,
        "setup_counts": {"liquidity_sweep": 20, "pullback": 20, "breakout": 10},
        "grade_counts": {"A+": 30, "A": 20},
        "per_symbol": {
            "RENDERUSDT": {
                "trades": 10,
                "net_profit": 5.0,
                "win_rate": 0.7,
                "profit_factor": 2.0,
                "roi": 10.0,
            },
            "TAOUSDT": {
                "trades": 40,
                "net_profit": 15.0,
                "win_rate": 0.55,
                "profit_factor": 1.4,
                "roi": 12.0,
            },
        },
        "per_symbol_attribution": {
            "RENDERUSDT": {
                "setup_counts": {"liquidity_sweep": 3, "pullback": 5, "breakout": 2},
                "grade_counts": {"A+": 6, "A": 4},
                "family_counts": {"liquidity": 3, "trend": 7},
                "family_setup_breakdown": {
                    "liquidity": {"liquidity_sweep": 3},
                    "trend": {"pullback": 5, "breakout": 2},
                },
                "family_margin_usdt": {"liquidity": 30.0, "trend": 70.0},
                "family_realized_pnl": {"liquidity": 2.0, "trend": 3.0},
                "trend_setup_realized_pnl": {"pullback": 2.0, "breakout": 1.0},
                "trend_setup_margin_usdt": {"pullback": 50.0, "breakout": 20.0},
            },
        },
        "per_symbol_trades": {"RENDERUSDT": [1.0, -0.5, 2.0]},
    }


def test_resolve_run_symbols_only_overrides_all():
    portfolio = ["TAOUSDT", "RENDERUSDT", "FETUSDT"]
    assert _resolve_backtest_run_symbols(
        use_all=True,
        portfolio_table=False,
        only=True,
        symbol_arg="FET",
        portfolio_syms=portfolio,
        report_symbols=["FETUSDT"],
    ) == ["FETUSDT"]


def test_resolve_run_symbols_all_with_symbol_report_filter():
    portfolio = ["TAOUSDT", "RENDERUSDT", "FETUSDT"]
    assert _resolve_backtest_run_symbols(
        use_all=True,
        portfolio_table=False,
        only=False,
        symbol_arg="FET",
        portfolio_syms=portfolio,
        report_symbols=["FETUSDT"],
    ) == portfolio


def test_filter_single_symbol_replaces_setup_and_attribution():
    filtered = _filter_result_for_report(_portfolio_result(), ["RENDER"])
    assert filtered["symbol"] == "RENDER"
    assert filtered["portfolio_symbols"] == "TAO, RENDER"
    assert filtered["setup_counts"] == {"liquidity_sweep": 3, "pullback": 5, "breakout": 2}
    assert filtered["grade_counts"] == {"A+": 6, "A": 4}
    liq = filtered["liquidity_attribution"]
    assert int(liq["total_trades"]) == 3
    trend = filtered["trend_attribution"]
    assert int(trend["total_trades"]) == 7
    assert int(trend["pullback"]) == 5
    assert int(trend["breakout"]) == 2
    report = format_backtest_report(filtered)
    assert "Portfolio: TAO, RENDER" in report
    assert "Symbol: RENDER" in report
    assert "Liquidity Sweep: 3" in report
    assert "Pullback: 5" in report


def test_apply_symbol_attribution_slice_profit_factor_from_trades():
    base = _portfolio_result()
    out = _apply_symbol_attribution_slice(dict(base), "RENDERUSDT")
    assert out["profit_factor"] is not None
    assert float(out["profit_factor"]) > 0


def test_symbol_day_window_payload_includes_setup_and_grades():
    filtered = _filter_result_for_report(_portfolio_result(), ["RENDER"])
    payload = _backtest_symbol_day_window_payload(filtered)
    assert payload["setup_counts"] == {"liquidity_sweep": 3, "pullback": 5, "breakout": 2}
    assert payload["grade_counts"] == {"A+": 6, "A": 4}
    assert payload["net_profit_usdt"] == 5.0
    assert "liquidity_reversal" in payload
    assert "pullback_trades" in payload["trend_following"]


def test_update_backtest_symbol_artifact_writes_namespaced_file(tmp_path, monkeypatch):
    import backtesting.backtest as bt

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(bt, "_artifacts_dir", lambda: artifacts)
    filtered = _filter_result_for_report(_portfolio_result(), ["RENDER"])
    _update_backtest_symbol_artifact(filtered, 7)
    data = json.loads((artifacts / "backtest_symbol.json").read_text())
    assert "7" in data
    assert data["7"]["portfolio_symbols"] == "TAO, RENDER"
    win = data["7"]["RENDER"]
    assert win["setup_counts"]["pullback"] == 5
    assert win["trend_following"]["pullback_trades"]["trades"] == 5


def test_update_backtest_symbol_baseline_artifact_matches_symbol_file(tmp_path, monkeypatch):
    import backtesting.backtest as bt

    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    monkeypatch.setattr(bt, "_artifacts_dir", lambda: artifacts)
    filtered = _filter_result_for_report(_portfolio_result(), ["RENDER"])
    _update_backtest_symbol_artifact(filtered, 7)
    _update_backtest_symbol_artifact(filtered, 7, baseline=True)
    regular = json.loads((artifacts / "backtest_symbol.json").read_text())
    baseline = json.loads((artifacts / "backtest_symbol_baseline.json").read_text())
    assert baseline == regular
