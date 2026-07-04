"""Liquidity SHORT should not fade 15m recovery rallies or V-reversals off recent lows."""

from __future__ import annotations

import pandas as pd

from strategy.liquidity_sweep_reversal import sweep_revesal_config as liq_cfg
from strategy.liquidity_sweep_reversal.base_sweep_revesal import LiquiditySweepReversalBase


def _ohlc_frame(
    closes: list[float],
    *,
    spread: float = 0.004,
) -> pd.DataFrame:
    rows = []
    for c in closes:
        c = float(c)
        rows.append(
            {
                "open": c * (1.0 - spread * 0.25),
                "high": c * (1.0 + spread),
                "low": c * (1.0 - spread),
                "close": c,
                "volume": 1000.0,
            }
        )
    return pd.DataFrame(rows)


def test_liquidity_short_blocked_on_15m_recovery_rally(monkeypatch) -> None:
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED", True, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_ENABLED", False, raising=False)
    strat = LiquiditySweepReversalBase()
    data_15m = _ohlc_frame([0.18 + i * 0.0015 for i in range(40)])

    assert strat._liquidity_short_recovery_rally(data_15m) is True
    assert (
        strat._liquidity_short_entry_block_reason(
            data_15m,
            None,
            0.237,
            symbol="FETUSDT",
        )
        == "liquidity_short_recovery_guard | 15m_recovery_rally"
    )


def test_liquidity_short_blocked_near_recent_swing_low(monkeypatch) -> None:
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED", False, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_ENABLED", True, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_LOOKBACK_15M", 24, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_MAX_PCT", 8, raising=False)
    strat = LiquiditySweepReversalBase()
    data_15m = _ohlc_frame([0.20] * 30)
    data_15m.loc[data_15m.index[-12], "low"] = 0.1827
    entry = 0.1960

    assert strat._liquidity_short_near_recent_swing_low(data_15m, None, entry) is True
    assert (
        strat._liquidity_short_entry_block_reason(
            data_15m,
            None,
            entry,
            symbol="FETUSDT",
        )
        == "liquidity_short_recovery_guard | near_swing_low"
    )


def test_liquidity_short_allowed_when_far_from_low_and_not_rallying(monkeypatch) -> None:
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED", True, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_ENABLED", True, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_LOOKBACK_15M", 24, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_MAX_PCT", 8, raising=False)
    strat = LiquiditySweepReversalBase()
    data_15m = _ohlc_frame([0.30 - i * 0.001 for i in range(40)])
    data_15m.loc[data_15m.index[-12], "low"] = 0.24
    entry = 0.265

    assert strat._liquidity_short_recovery_rally(data_15m) is False
    assert strat._liquidity_short_near_recent_swing_low(data_15m, None, entry) is False
    assert strat._liquidity_short_entry_block_reason(data_15m, None, entry, symbol="FETUSDT") is None


def test_liquidity_short_recovery_guards_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_RECOVERY_GUARD_ENABLED", False, raising=False)
    monkeypatch.setattr(liq_cfg, "LIQUIDITY_SHORT_NEAR_SWING_LOW_ENABLED", False, raising=False)
    strat = LiquiditySweepReversalBase()
    data_15m = _ohlc_frame([0.18 + i * 0.0015 for i in range(40)])

    assert strat._liquidity_short_entry_block_reason(data_15m, None, 0.237, symbol="FETUSDT") is None
