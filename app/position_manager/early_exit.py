from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from indicators import calculate_atr
from monitoring.logger import log


SIGNAL_BREAKOUT_FAILURE = "breakout_failure"
SIGNAL_STRUCTURE_BREAK = "structure_break"
SIGNAL_STRONG_REJECTION = "strong_rejection"


@dataclass
class EarlyExitResult:
    should_exit: bool
    confidence: float
    signals: list[str] = field(default_factory=list)


def evaluate_early_exit(
    *,
    direction: str,
    entry_price: float | None,
    current_price: float,
    current_roi: float,
    breakout_level: float | None,
    last_15m_high: float | None,
    last_15m_low: float | None,
    current_15m_close: float | None,
    candle_opens: list[float],
    candle_closes: list[float],
    candle_highs: list[float],
    candle_lows: list[float],
    candle_volumes: list[float],
    time_since_tp1: float | None,
    symbol: str = "",
) -> EarlyExitResult:
    if time_since_tp1 is not None:
        return EarlyExitResult(should_exit=False, confidence=0.0, signals=[])
    if not candle_closes or len(candle_closes) < 2:
        return EarlyExitResult(should_exit=False, confidence=0.0, signals=[])
    if candle_highs is None or candle_lows is None or len(candle_highs) < 15 or len(candle_lows) < 15:
        return EarlyExitResult(should_exit=False, confidence=0.0, signals=[])
    is_long = str(direction).upper() == "LONG"
    triggered: list[str] = []
    last_close = float(candle_closes[-1])

    if breakout_level is not None and breakout_level > 0.0:
        if is_long:
            if last_close < float(breakout_level):
                triggered.append(SIGNAL_BREAKOUT_FAILURE)
        else:
            if last_close > float(breakout_level):
                triggered.append(SIGNAL_BREAKOUT_FAILURE)

    if last_15m_high is not None and last_15m_low is not None and current_15m_close is not None:
        c15_close = float(current_15m_close)
        if is_long:
            if c15_close < float(last_15m_low):
                triggered.append(SIGNAL_STRUCTURE_BREAK)
        else:
            if c15_close > float(last_15m_high):
                triggered.append(SIGNAL_STRUCTURE_BREAK)

    if (
        candle_highs is not None
        and candle_lows is not None
        and len(candle_highs) >= 15
        and len(candle_lows) >= 15
        and len(candle_closes) >= 15
        and len(candle_opens) >= 1
        and len(candle_volumes) >= 20
    ):
        import numpy as np

        atr_series = calculate_atr(
            _candle_df(candle_highs, candle_lows, candle_closes),
            14,
        )
        atr_value = float(atr_series.iloc[-1]) if not atr_series.empty else None

        last_open = float(candle_opens[-1])
        last_high = float(candle_highs[-1])
        last_low = float(candle_lows[-1])
        last_vol = float(candle_volumes[-1])

        vol_tail = [float(v) for v in candle_volumes[-20:]]
        avg_vol_20 = float(np.mean(vol_tail)) if vol_tail else 0.0

        if atr_value is not None and atr_value > 1e-12 and avg_vol_20 > 1e-12:
            body_size = abs(last_close - last_open)
            is_bearish = last_close < last_open
            is_bullish = last_close > last_open

            if is_long:
                if is_bearish and body_size > atr_value and last_vol > avg_vol_20 * 1.5:
                    triggered.append(SIGNAL_STRONG_REJECTION)
            else:
                if is_bullish and body_size > atr_value and last_vol > avg_vol_20 * 1.5:
                    triggered.append(SIGNAL_STRONG_REJECTION)

    signal_count = len(triggered)

    if signal_count >= 2:
        should_exit = True
    else:
        should_exit = False

    confidence: float = {0: 0.0, 1: 0.0, 2: 70.0, 3: 95.0}.get(signal_count, 0.0)

    if should_exit:
        log(
            f"[EARLY EXIT] {symbol} | side={direction} "
            f"entry={entry_price or 0:.4f} "
            f"current={current_price:.4f} "
            f"roi={current_roi:.2f}% "
            f"signals={triggered} "
            f"confidence={confidence:.1f}% "
            f"decision=EXIT"
        )

    return EarlyExitResult(
        should_exit=should_exit,
        confidence=confidence,
        signals=triggered,
    )


def _candle_df(
    highs: list[float],
    lows: list[float],
    closes: list[float],
) -> Any:
    import pandas as pd

    n = min(len(highs), len(lows), len(closes))
    return pd.DataFrame({
        "high": [float(highs[i]) for i in range(n)],
        "low": [float(lows[i]) for i in range(n)],
        "close": [float(closes[i]) for i in range(n)],
    })
