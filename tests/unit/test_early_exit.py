from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from position_management.early_exit import (
    EarlyExitResult,
    evaluate_early_exit,
    SIGNAL_BREAKOUT_FAILURE,
    SIGNAL_STRUCTURE_BREAK,
    SIGNAL_STRONG_REJECTION,
)
from indicators import calculate_atr


def _rising_prices(n: int, start: float = 100.0, step: float = 0.1) -> list[float]:
    return [start + i * step for i in range(n)]


def _flat_prices(n: int, price: float = 100.0) -> list[float]:
    return [price] * n


def _highs_from_closes(closes: list[float], spread: float = 0.05) -> list[float]:
    return [c + spread for c in closes]


def _lows_from_closes(closes: list[float], spread: float = 0.05) -> list[float]:
    return [c - spread for c in closes]


def _volumes(n: int, base: float = 1000.0) -> list[float]:
    return [base] * n


def _high_volume(n: int, base: float = 2000.0) -> list[float]:
    return [base] * n


def _bearish_candle_body(price: float, size: float = 1.5) -> tuple[float, float]:
    return price + size, price


def _bullish_candle_body(price: float, size: float = 1.5) -> tuple[float, float]:
    return price - size, price


def _candle_high_low(
    open_p: float, close_p: float, spread: float = 0.2
) -> tuple[float, float]:
    hi = max(open_p, close_p) + spread
    lo = min(open_p, close_p) - spread
    return hi, lo


_N = 64


class TestEarlyExitUnit:
    def test_tp1_hit_blocks_early_exit(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=105.0,
            current_roi=5.0,
            breakout_level=None,
            last_15m_high=102.0,
            last_15m_low=101.0,
            current_15m_close=98.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=1000.0,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False
        assert result.signals == []

    def test_single_signal_never_exits(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=100.5,
            current_roi=0.5,
            breakout_level=99.0,
            last_15m_high=102.0,
            last_15m_low=101.0,
            current_15m_close=100.5,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False

    def test_breakout_failure_triggers_single_still_holds(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        closes[-1] = 97.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        opens[-1] = 98.0
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=97.0,
            current_roi=-3.0,
            breakout_level=98.0,
            last_15m_high=102.0,
            last_15m_low=96.0,
            current_15m_close=100.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False
        assert SIGNAL_BREAKOUT_FAILURE in result.signals

    def test_breakout_failure_plus_structure_break_exits(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        closes[-1] = 97.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        opens[-1] = 98.0
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=97.0,
            current_roi=-3.0,
            breakout_level=98.0,
            last_15m_high=102.0,
            last_15m_low=100.0,
            current_15m_close=99.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is True
        assert SIGNAL_BREAKOUT_FAILURE in result.signals
        assert SIGNAL_STRUCTURE_BREAK in result.signals
        assert result.confidence == 70.0

    def test_three_signals_exits_with_95_confidence(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        bear_open, bear_close = _bearish_candle_body(97.0, size=3.0)
        closes[-1] = bear_close
        highs = _highs_from_closes(closes, spread=0.2)
        lows = _lows_from_closes(closes, spread=0.2)
        opens = [c - 0.05 for c in closes]
        opens[-1] = bear_open
        bh, bl = _candle_high_low(bear_open, bear_close)
        highs[-1] = bh
        lows[-1] = bl
        vols = _volumes(_N)
        vols[-1] = 3000.0
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=97.0,
            current_roi=-3.0,
            breakout_level=98.0,
            last_15m_high=102.0,
            last_15m_low=100.0,
            current_15m_close=99.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is True
        assert result.confidence == 95.0
        assert len(result.signals) == 3

    def test_short_side_breakout_failure(self) -> None:
        closes = _falling_prices(_N, start=100.0)
        closes[-1] = 103.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c + 0.05 for c in closes]
        opens[-1] = 102.0
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="SHORT",
            entry_price=100.0,
            current_price=103.0,
            current_roi=-3.0,
            breakout_level=102.0,
            last_15m_high=105.0,
            last_15m_low=99.0,
            current_15m_close=103.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False
        assert SIGNAL_BREAKOUT_FAILURE in result.signals

    def test_short_side_two_signals_exits(self) -> None:
        closes = _falling_prices(_N, start=100.0)
        closes[-1] = 103.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c + 0.05 for c in closes]
        opens[-1] = 102.0
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="SHORT",
            entry_price=100.0,
            current_price=103.0,
            current_roi=-3.0,
            breakout_level=102.0,
            last_15m_high=100.0,
            last_15m_low=99.0,
            current_15m_close=104.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is True
        assert len(result.signals) >= 2

    def test_missing_atr_does_not_exit(self) -> None:
        closes = [100.0]
        highs = [100.5]
        lows = [99.5]
        opens = [100.0]
        vols = [1000.0]
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=99.0,
            current_roi=-1.0,
            breakout_level=98.0,
            last_15m_high=102.0,
            last_15m_low=101.0,
            current_15m_close=100.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False

    def test_missing_structure_does_not_exit(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        closes[-1] = 97.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=97.0,
            current_roi=-3.0,
            breakout_level=98.0,
            last_15m_high=None,
            last_15m_low=None,
            current_15m_close=None,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False

    def test_insufficient_candles_does_not_exit(self) -> None:
        closes = [100.0, 101.0]
        highs = [100.5, 101.5]
        lows = [99.5, 100.5]
        opens = [100.0, 100.5]
        vols = [1000.0, 1100.0]
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=101.0,
            current_roi=1.0,
            breakout_level=98.0,
            last_15m_high=102.0,
            last_15m_low=101.0,
            current_15m_close=100.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False

    def test_strong_rejection_adds_third_signal(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        closes[-1] = 97.0
        highs = _highs_from_closes(closes, spread=0.2)
        lows = _lows_from_closes(closes, spread=0.2)
        opens = [c - 0.05 for c in closes]
        opens[-1] = 100.5
        bh, bl = _candle_high_low(100.5, 97.0)
        highs[-1] = bh
        lows[-1] = bl
        vols = _volumes(_N)
        vols[-1] = 3000.0
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=97.0,
            current_roi=-3.0,
            breakout_level=98.0,
            last_15m_high=102.0,
            last_15m_low=100.0,
            current_15m_close=99.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is True
        assert SIGNAL_STRONG_REJECTION in result.signals
        assert len(result.signals) >= 2

    def test_short_strong_rejection(self) -> None:
        closes = _falling_prices(_N, start=100.0)
        closes[-1] = 103.0
        highs = _highs_from_closes(closes, spread=0.2)
        lows = _lows_from_closes(closes, spread=0.2)
        opens = [c + 0.05 for c in closes]
        opens[-1] = 100.0
        bh, bl = _candle_high_low(100.0, 103.0)
        highs[-1] = bh
        lows[-1] = bl
        vols = _volumes(_N)
        vols[-1] = 3000.0
        result = evaluate_early_exit(
            direction="SHORT",
            entry_price=100.0,
            current_price=103.0,
            current_roi=-3.0,
            breakout_level=102.0,
            last_15m_high=100.0,
            last_15m_low=99.0,
            current_15m_close=104.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is True
        assert SIGNAL_STRONG_REJECTION in result.signals

    def test_no_breakout_level_no_breakout_failure(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        closes[-1] = 97.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=97.0,
            current_roi=-3.0,
            breakout_level=None,
            last_15m_high=102.0,
            last_15m_low=99.0,
            current_15m_close=100.5,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False
        assert len(result.signals) == 0

    def test_no_breakout_level_skips_breakout_failure_signal(self) -> None:
        closes = _rising_prices(_N, start=100.0)
        closes[-1] = 98.0
        highs = _highs_from_closes(closes)
        lows = _lows_from_closes(closes)
        opens = [c - 0.05 for c in closes]
        vols = _volumes(_N)
        result = evaluate_early_exit(
            direction="LONG",
            entry_price=100.0,
            current_price=98.0,
            current_roi=-2.0,
            breakout_level=None,
            last_15m_high=102.0,
            last_15m_low=99.0,
            current_15m_close=100.0,
            candle_opens=opens,
            candle_closes=closes,
            candle_highs=highs,
            candle_lows=lows,
            candle_volumes=vols,
            time_since_tp1=None,
            symbol="TAOUSDT",
        )
        assert result.should_exit is False
        assert SIGNAL_BREAKOUT_FAILURE not in result.signals


def _falling_prices(n: int, start: float = 100.0, step: float = 0.1) -> list[float]:
    return [start - i * step for i in range(n)]
