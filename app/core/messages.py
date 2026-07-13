from __future__ import annotations

from typing import Any


def no_market_data(symbol: str, timestamp: Any) -> str:
    return f"{symbol} {timestamp}: no market data"


def not_enough_history(symbol: str, timestamp: Any) -> str:
    return f"{symbol} {timestamp}: not enough history"


def no_setup_detected(symbol: str, timestamp: Any) -> str:
    return f"{symbol} {timestamp}: no setup detected"


def setup_build_failed(symbol: str, timestamp: Any) -> str:
    return f"{symbol} {timestamp}: setup build failed"


def signal_build_failed(symbol: str, timestamp: Any) -> str:
    return f"{symbol} {timestamp}: signal build failed"


def risk_rejected(symbol: str, timestamp: Any, reason: str) -> str:
    return f"{symbol} {timestamp}: risk rejected: {reason}"


def order_plan_failed(symbol: str, timestamp: Any) -> str:
    return f"{symbol} {timestamp}: order plan build failed"
