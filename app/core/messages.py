from __future__ import annotations


def no_market_data() -> str:
    return "no market data"


def not_enough_history() -> str:
    return "not enough history"


def no_setup_detected() -> str:
    return "no setup detected"


def setup_build_failed() -> str:
    return "setup build failed"


def signal_build_failed() -> str:
    return "signal build failed"


def risk_rejected(reason: str) -> str:
    return f"risk rejected: {reason}"


def order_plan_failed() -> str:
    return "order plan build failed"
