from __future__ import annotations

import pytest

from app.monitoring.messages import (
    format_entry_filled_console_line,
    format_open_strategy_setup_labels,
    format_position_open_standard_line,
)

pytestmark = pytest.mark.unit


def test_format_open_strategy_setup_labels_trend_breakout() -> None:
    s, u = format_open_strategy_setup_labels(
        strategy_family="trend_following",
        setup_type="breakout",
    )
    assert s == "Trend Following"
    assert u == "Breakout"


def test_format_open_strategy_setup_labels_liquidity() -> None:
    s, u = format_open_strategy_setup_labels(
        strategy_family="liquidity",
        setup_type="liquidity_sweep",
    )
    assert s == "Liquidity"
    assert u == "Liquidity Sweep Reversal"


def test_format_entry_filled_console_line_manual_open() -> None:
    line = format_entry_filled_console_line(
        mode="demo",
        symbol="TAOUSDT",
        direction="SHORT",
        hedge_on=True,
        leverage=10,
        size_usdt=10.0,
        entry=282.75,
        stop_loss=284.44,
        tp1=281.90,
        tp2=281.05,
        tp3=280.20,
        price_decimals=2,
    )
    assert line == (
        "[DEMO] | [TAOUSDT] | [SHORT] | Hedge=ON | Lev=10x | Size=10 USDT | "
        "Entry=282.75 | SL=284.44 | TP1=281.90| TP2=281.05 | TP3=280.20 | Entry Filled"
    )


def test_format_position_open_standard_line_includes_strategy_setup() -> None:
    line = format_position_open_standard_line(
        symbol="TAOUSDT",
        entry=259.24,
        stop_loss=260.21,
        size_usdt=300.0,
        leverage=10,
        risk_usdt=1.12,
        tp1=257.31,
        tp2=256.12,
        tp3=254.34,
        strategy_family="trend_following",
        setup_type="pullback",
    )
    assert "Strategy: Trend Following | Setup: Pullback |" in line
    assert "Entry: 259.24" in line
