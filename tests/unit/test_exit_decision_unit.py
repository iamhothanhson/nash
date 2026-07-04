from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.position_management.exit_manager import ExitManagerConfig, decide_exit


def _cfg() -> ExitManagerConfig:
    return ExitManagerConfig(
        min_hold_seconds=30.0,
        adx_threshold=20.0,
        min_volume_ratio=1.0,
        mfe_drawdown_threshold=0.35,
        mfe_drawdown_threshold_strong_trend=0.40,
        min_roi_mfe_drawdown_apply=0.0,
        long_hold_mfe_tighten_after_seconds=999999.0,
        long_hold_mfe_tighten_sub=0.0,
        mfe_tighten_step1_after_seconds=999999.0,
        mfe_tighten_step1_sub=0.0,
        mfe_tighten_step2_after_seconds=999999.0,
        mfe_tighten_step2_sub=0.0,
        mfe_profit_lock_after_seconds=999999.0,
        mfe_profit_lock_min_peak_roi=999999.0,
        mfe_profit_lock_min_roi=-999999.0,
        mfe_require_structure_break=True,
        mfe_immediate_on_threshold=False,
        min_hold_pre_tp1_seconds=2100.0,
        min_hold_after_tp1_seconds=900.0,
        ema_fast=9,
        ema_slow=21,
        min_consecutive_opposite_candles=2,
        min_momentum_weak_signals=2,
    )


_POST_TP1 = 1000.0  # above min_hold_after_tp1_seconds (900) in _cfg()


class TestExitDecisionUnit:
    def test_mfe_skips_when_peak_below_min_apply(self) -> None:
        cfg = replace(_cfg(), min_roi_mfe_drawdown_apply=7.0, mfe_immediate_on_threshold=True)
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 5.0}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=5.0,
            volume_ratio=0.8,
            adx=10.0,
            exit_manager=cfg,
        )
        assert out["reason"] != "mfe_drawdown_exceeded"

    def test_mfe_closes_when_peak_at_min_apply(self) -> None:
        cfg = replace(_cfg(), min_roi_mfe_drawdown_apply=7.0, mfe_immediate_on_threshold=True)
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=1.0,
            roi_history=[{"t": 50.0, "roi": 8.0}, {"t": 120.0, "roi": 1.0}],
            max_roi_seen=8.0,
            volume_ratio=0.8,
            adx=10.0,
            time_since_tp1=_POST_TP1,
            exit_manager=cfg,
        )
        assert out["action"] == "CLOSE"
        assert out["reason"] == "mfe_drawdown_exceeded"

    def test_mfe_pre_tp1_holds_despite_giveback(self) -> None:
        cfg = replace(_cfg(), min_roi_mfe_drawdown_apply=7.0, mfe_immediate_on_threshold=True)
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=1.0,
            roi_history=[{"t": 50.0, "roi": 8.0}, {"t": 120.0, "roi": 1.0}],
            max_roi_seen=8.0,
            volume_ratio=0.8,
            adx=10.0,
            time_since_tp1=None,
            exit_manager=cfg,
        )
        assert out["reason"] != "mfe_drawdown_exceeded"

    def test_pre_tp1_min_hold_uses_min_hold_gate_for_stagnant_close(self) -> None:
        cfg = replace(_cfg(), min_hold_pre_tp1_seconds=7200.0)
        out = decide_exit(
            time_in_trade=3600.0,
            current_roi=0.1,
            roi_history=[{"t": 100.0, "roi": 0.5}, {"t": 3600.0, "roi": 0.1}],
            max_roi_seen=0.5,
            volume_ratio=0.8,
            adx=10.0,
            time_since_tp1=None,
            exit_manager=cfg,
        )
        assert out["action"] == "HOLD"
        assert out["reason"] == "min_hold_gate"

    def test_min_hold_gate(self) -> None:
        out = decide_exit(
            time_in_trade=10.0,
            current_roi=0.1,
            roi_history=[{"t": 1.0, "roi": 0.1}],
            max_roi_seen=0.1,
            volume_ratio=1.2,
            adx=25.0,
            exit_manager=_cfg(),
        )
        assert out["action"] == "HOLD"
        assert out["reason"] == "min_hold_gate"

    def test_mfe_drawdown_closes_when_not_strong_trend(self) -> None:
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.0}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.1,
            volume_ratio=0.8,
            adx=10.0,
            direction="LONG",
            candle_opens=[100.0, 101.0, 101.5],
            candle_closes=[101.0, 100.4, 99.8],
            candle_volumes=[1000.0, 1100.0, 1300.0],
            time_since_tp1=_POST_TP1,
            exit_manager=_cfg(),
        )
        assert out["action"] == "CLOSE"
        assert out["reason"] == "mfe_drawdown_exceeded"

    def test_mfe_drawdown_holds_in_strong_trend_below_strong_threshold(self) -> None:
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.0}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.1,
            volume_ratio=1.2,
            adx=25.0,
            direction="LONG",
            candle_opens=[100.0, 101.0, 101.5],
            candle_closes=[101.0, 100.9, 100.8],
            candle_volumes=[1000.0, 980.0, 960.0],
            time_since_tp1=_POST_TP1,
            exit_manager=_cfg(),
        )
        assert out["action"] == "HOLD"

    def test_mfe_drawdown_closes_in_strong_trend_above_strong_threshold(self) -> None:
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.5}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.5,
            volume_ratio=1.2,
            adx=25.0,
            direction="LONG",
            candle_opens=[100.0, 101.0, 102.0],
            candle_closes=[101.0, 99.5, 98.0],
            candle_volumes=[1000.0, 1300.0, 1600.0],
            time_since_tp1=_POST_TP1,
            exit_manager=_cfg(),
        )
        assert out["action"] == "CLOSE"
        assert out["reason"] == "mfe_drawdown_exceeded"

    def test_tp1_grace_period_holds_even_when_conditions_match(self) -> None:
        out = decide_exit(
            time_in_trade=240.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.5}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.5,
            volume_ratio=1.2,
            adx=25.0,
            direction="LONG",
            candle_opens=[100.0, 101.0, 102.0],
            candle_closes=[101.0, 99.5, 98.0],
            candle_volumes=[1000.0, 1300.0, 1600.0],
            time_since_tp1=60.0,
            exit_manager=_cfg(),
        )
        assert out["action"] == "HOLD"
        assert out["reason"] == "tp1_grace_period"

    def test_mfe_15m_no_structure_break_holds_despite_weak_5m_momentum(self) -> None:
        """MFE drawdown + weak 5m momentum must not exit without 15m structure break."""
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.1}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.1,
            volume_ratio=0.8,
            adx=10.0,
            direction="LONG",
            candle_opens=[100.0, 101.0, 101.5],
            candle_closes=[101.0, 100.4, 99.8],
            candle_volumes=[1000.0, 1100.0, 1300.0],
            time_since_tp1=_POST_TP1,
            exit_manager=_cfg(),
            last_15m_high=102.0,
            last_15m_low=99.5,
            current_15m_close=100.0,
            symbol="BTCUSDT",
        )
        assert out["action"] == "HOLD"
        assert out["reason"] == "mfe_pullback_hold"
        assert out["metrics"].get("structure_break") is False

    def test_mfe_15m_structure_break_closes_without_weak_5m_momentum(self) -> None:
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.1}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.1,
            volume_ratio=0.8,
            adx=10.0,
            direction="LONG",
            candle_opens=[100.0, 100.0, 100.0],
            candle_closes=[100.1, 100.2, 100.3],
            candle_volumes=[1000.0, 1000.0, 1000.0],
            time_since_tp1=_POST_TP1,
            exit_manager=_cfg(),
            last_15m_high=102.0,
            last_15m_low=99.5,
            current_15m_close=99.0,
            symbol="BTCUSDT",
        )
        assert out["action"] == "CLOSE"
        assert out["reason"] == "mfe_drawdown_exceeded"
        assert out["metrics"].get("structure_break") is True

    def test_mfe_immediate_on_threshold_closes_without_momentum_gates(self) -> None:
        """Bank profit when giveback >= threshold; do not hold for ROI recovery."""
        cfg = replace(
            _cfg(),
            mfe_immediate_on_threshold=True,
            mfe_require_structure_break=True,
            mfe_drawdown_threshold=0.35,
            mfe_drawdown_threshold_strong_trend=0.35,
        )
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=4.0,
            roi_history=[{"t": 50.0, "roi": 10.0}, {"t": 120.0, "roi": 4.0}],
            max_roi_seen=10.0,
            volume_ratio=1.2,
            adx=25.0,
            direction="LONG",
            candle_opens=[100.0, 100.0, 100.0],
            candle_closes=[100.1, 100.2, 100.3],
            candle_volumes=[1000.0, 1000.0, 1000.0],
            time_since_tp1=_POST_TP1,
            exit_manager=cfg,
            last_15m_high=105.0,
            last_15m_low=99.0,
            current_15m_close=100.5,
            symbol="TAOUSDT",
        )
        assert out["action"] == "CLOSE"
        assert out["reason"] == "mfe_drawdown_exceeded"

    def test_mfe_giveback_closes_without_structure_when_flag_off(self) -> None:
        cfg = replace(_cfg(), mfe_require_structure_break=False)
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=4.0,
            roi_history=[{"t": 50.0, "roi": 10.0}, {"t": 120.0, "roi": 4.0}],
            max_roi_seen=10.0,
            volume_ratio=0.8,
            adx=15.0,
            direction="LONG",
            candle_opens=[100.0, 101.0, 102.0],
            candle_closes=[101.0, 100.5, 100.8],
            candle_volumes=[1000.0, 1000.0, 1000.0],
            time_since_tp1=_POST_TP1,
            exit_manager=cfg,
            last_15m_high=105.0,
            last_15m_low=99.0,
            current_15m_close=100.5,
            symbol="TAOUSDT",
        )
        assert out["action"] == "CLOSE"
        assert out["reason"] == "mfe_drawdown_exceeded"
        assert out["metrics"].get("structure_break") is False

    def test_mfe_strong_trend_requires_structure_and_momentum(self) -> None:
        out = decide_exit(
            time_in_trade=120.0,
            current_roi=0.1,
            roi_history=[{"t": 50.0, "roi": 1.5}, {"t": 120.0, "roi": 0.1}],
            max_roi_seen=1.5,
            volume_ratio=1.2,
            adx=25.0,
            direction="LONG",
            candle_opens=[100.0, 100.0, 100.0],
            candle_closes=[100.1, 100.2, 100.3],
            candle_volumes=[1000.0, 1000.0, 1000.0],
            time_since_tp1=_POST_TP1,
            exit_manager=_cfg(),
            last_15m_high=102.0,
            last_15m_low=99.5,
            current_15m_close=99.0,
            symbol="BTCUSDT",
        )
        assert out["action"] == "HOLD"
        assert out["reason"] == "mfe_pullback_hold"
