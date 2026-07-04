from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from coins.loader import (
    get_coin_config,
    max_breakout_retest_positions_for,
    max_opened_positions_for,
    price_decimals_from_binance_tick,
    price_rounding_decimal,
    resolve_max_tp1_distance,
    resolve_max_tp2_distance,
    symbol_at_per_symbol_cap,
    symbol_entry_block_reason,
    symbol_entry_blocked,
    trend_setup_slot_block_reason,
)


def test_tao_max_opened_positions_single_book() -> None:
    assert max_opened_positions_for("TAOUSDT") == 1
    assert max_breakout_retest_positions_for("TAOUSDT") == 1


def test_tao_config_has_no_tp_distance_caps() -> None:
    cfg = get_coin_config("TAOUSDT")
    assert cfg.get("max_tp1_pct") is None
    assert cfg.get("max_tp2_pct") is None
    assert resolve_max_tp1_distance(cfg) is None
    assert resolve_max_tp2_distance(cfg) is None


def test_render_max_opened_positions_single_book() -> None:
    assert max_opened_positions_for("RENDERUSDT") == 1
    assert max_breakout_retest_positions_for("RENDERUSDT") == 1


def test_fet_max_opened_positions_single_book() -> None:
    assert max_opened_positions_for("FETUSDT") == 1
    assert max_breakout_retest_positions_for("FETUSDT") == 1


def test_fet_config_loads() -> None:
    cfg = get_coin_config("FETUSDT")
    assert int(cfg["min_setup_score"]) == 8
    assert int(cfg.get("price_rounding_decimal", 0)) == 4
    assert float(cfg.get("atr_multiplier", 1.0)) == 1.0
    assert cfg.get("max_tp1_pct") is None
    assert cfg.get("max_tp2_pct") is None
    assert cfg.get("enforce_min_risk_reward_multiple") is False


def test_render_price_decimals_config() -> None:
    cfg = get_coin_config("RENDERUSDT")
    assert int(cfg.get("price_rounding_decimal", 0)) == 3
    assert cfg.get("price_rounding_decimal_from_exchange") is not True
    assert price_rounding_decimal("RENDERUSDT") == 3


def test_price_decimals_from_binance_tick() -> None:
    assert price_decimals_from_binance_tick("0.10") == 2
    assert price_decimals_from_binance_tick("0.0001") == 4
    assert price_decimals_from_binance_tick("0.01") == 2
    assert price_decimals_from_binance_tick("0.0010000") == 7


def test_symbol_at_cap_blocks_third_tao_book() -> None:
    counts = {"TAOUSDT": 2}
    assert symbol_at_per_symbol_cap("TAOUSDT", counts) is True


def test_breakout_then_retest_allowed() -> None:
    from types import SimpleNamespace

    positions = [
        SimpleNamespace(
            symbol="TAOUSDT",
            closed=False,
            qty_open=1.0,
            direction="LONG",
            strategy_family="trend_following",
            setup_type="breakout",
        )
    ]
    assert (
        trend_setup_slot_block_reason(
            positions,
            symbol="TAOUSDT",
            setup_type="breakout_retest",
            direction="LONG",
            strategy_family="trend_following",
        )
        is None
    )
    assert symbol_entry_blocked(
        "TAOUSDT",
        {"TAOUSDT": 1},
        setup_type="breakout_retest",
        direction="LONG",
        strategy_family="trend_following",
        open_positions=positions,
    )
    assert symbol_entry_blocked(
        "TAOUSDT",
        {"TAOUSDT": 1},
        setup_type="breakout",
        direction="LONG",
        strategy_family="trend_following",
        open_positions=positions,
    )


def test_retest_allowed_without_breakout() -> None:
    assert (
        trend_setup_slot_block_reason(
            [],
            symbol="TAOUSDT",
            setup_type="breakout_retest",
            direction="LONG",
            strategy_family="trend_following",
        )
        is None
    )


def test_retest_open_allows_breakout() -> None:
    from types import SimpleNamespace

    positions = [
        SimpleNamespace(
            symbol="TAOUSDT",
            closed=False,
            qty_open=1.0,
            direction="LONG",
            strategy_family="trend_following",
            setup_type="breakout_retest",
        )
    ]
    assert (
        trend_setup_slot_block_reason(
            positions,
            symbol="TAOUSDT",
            setup_type="breakout",
            direction="LONG",
            strategy_family="trend_following",
        )
        is None
    )
    assert symbol_entry_blocked(
        "TAOUSDT",
        {"TAOUSDT": 1},
        setup_type="breakout",
        direction="LONG",
        strategy_family="trend_following",
        open_positions=positions,
    )


def test_pullback_blocks_breakout_and_retest() -> None:
    from types import SimpleNamespace

    positions = [
        SimpleNamespace(
            symbol="TAOUSDT",
            closed=False,
            qty_open=1.0,
            direction="LONG",
            strategy_family="trend_following",
            setup_type="pullback",
        )
    ]
    for setup in ("breakout", "breakout_retest"):
        reason = trend_setup_slot_block_reason(
            positions,
            symbol="TAOUSDT",
            setup_type=setup,
            direction="LONG",
            strategy_family="trend_following",
        )
        assert reason == "trend slot blocked: breakout/retest vs pullback"


def test_breakout_blocks_pullback() -> None:
    from types import SimpleNamespace

    positions = [
        SimpleNamespace(
            symbol="TAOUSDT",
            closed=False,
            qty_open=1.0,
            direction="LONG",
            strategy_family="trend_following",
            setup_type="breakout",
        )
    ]
    reason = trend_setup_slot_block_reason(
        positions,
        symbol="TAOUSDT",
        setup_type="pullback",
        direction="LONG",
        strategy_family="trend_following",
    )
    assert reason == "trend slot blocked: pullback vs breakout/retest"


def test_liquidity_blocks_trend_and_vice_versa() -> None:
    from types import SimpleNamespace

    liquidity_open = [
        SimpleNamespace(
            symbol="TAOUSDT",
            closed=False,
            qty_open=1.0,
            direction="LONG",
            strategy_family="liquidity",
            setup_type="liquidity_sweep",
        )
    ]
    trend_block = symbol_entry_block_reason(
        "TAOUSDT",
        {"TAOUSDT": 1},
        setup_type="breakout",
        direction="LONG",
        strategy_family="trend_following",
        open_positions=liquidity_open,
    )
    assert trend_block == "trend blocked: liquidity_sweep_reversal open"

    trend_open = [
        SimpleNamespace(
            symbol="TAOUSDT",
            closed=False,
            qty_open=1.0,
            direction="LONG",
            strategy_family="trend_following",
            setup_type="breakout",
        )
    ]
    liq_block = symbol_entry_block_reason(
        "TAOUSDT",
        {"TAOUSDT": 1},
        setup_type="liquidity_sweep",
        direction="LONG",
        strategy_family="liquidity",
        open_positions=trend_open,
    )
    assert liq_block == "liquidity blocked: trend following open"
