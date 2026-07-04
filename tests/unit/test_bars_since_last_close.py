from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.coins.loader import resolve_bars_since_last_close_min
from app.trading.symbol_close_tracking import (
    closed_5m_bar_ts_from_iso,
    count_bars_since_close_5m,
    floor_ts_to_5m_bar,
    get_last_close_bar_ts,
    log_entry_after_bars_skip,
    record_symbol_close_bar,
    reset_symbol_close_tracking,
)

pytestmark = pytest.mark.unit


def setup_function() -> None:
    reset_symbol_close_tracking()


def test_resolve_bars_since_last_close_min_from_coin_config() -> None:
    assert resolve_bars_since_last_close_min("FETUSDT") == 6
    assert resolve_bars_since_last_close_min("TAOUSDT") == 6
    assert resolve_bars_since_last_close_min("RENDERUSDT") == 6


def test_count_bars_since_close_5m() -> None:
    assert count_bars_since_close_5m(latest_closed_bar_ts=1500.0, last_close_bar_ts=None) is None
    assert count_bars_since_close_5m(latest_closed_bar_ts=None, last_close_bar_ts=1200.0) is None
    assert count_bars_since_close_5m(latest_closed_bar_ts=1200.0, last_close_bar_ts=1200.0) == 0
    assert count_bars_since_close_5m(latest_closed_bar_ts=1500.0, last_close_bar_ts=1200.0) == 1
    assert count_bars_since_close_5m(latest_closed_bar_ts=7200.0, last_close_bar_ts=1200.0) == 20


def test_record_symbol_close_bar_tracks_latest() -> None:
    record_symbol_close_bar("FETUSDT", 1000.0)
    record_symbol_close_bar("FETUSDT", 1600.0)
    assert get_last_close_bar_ts("FETUSDT") == 1600.0


def test_closed_5m_bar_ts_from_iso_floors_to_bar() -> None:
    ts = closed_5m_bar_ts_from_iso("2026-06-03T03:42:30+00:00")
    assert ts == floor_ts_to_5m_bar(ts)
    assert int(ts) % 300 == 0


def test_bars_since_gate_blocks_before_coin_min() -> None:
    min_bars = resolve_bars_since_last_close_min("FETUSDT")
    bars_since = 5
    assert min_bars == 6
    assert min_bars > 0 and bars_since is not None and bars_since < min_bars


def test_log_entry_after_bars_skip_respects_debug_flag() -> None:
    os.environ["ENTRY_AFTER_BARS_DEBUG"] = "false"
    import config.settings as settings_mod

    importlib.reload(settings_mod)
    import trading.symbol_close_tracking as tracking_mod

    importlib.reload(tracking_mod)
    with patch("monitoring.logger.log") as mock_log:
        tracking_mod.log_entry_after_bars_skip("FETUSDT", 3, 6)
        mock_log.assert_not_called()

    os.environ["ENTRY_AFTER_BARS_DEBUG"] = "true"
    importlib.reload(settings_mod)
    importlib.reload(tracking_mod)
    with patch("monitoring.logger.log") as mock_log:
        tracking_mod.log_entry_after_bars_skip("FETUSDT", 3, 6)
        mock_log.assert_called_once_with(
            "[SKIP] FETUSDT | bars_since_last_close 3 < 6",
            strip_setup=False,
        )
    os.environ.pop("ENTRY_AFTER_BARS_DEBUG", None)
    importlib.reload(settings_mod)
    importlib.reload(tracking_mod)
