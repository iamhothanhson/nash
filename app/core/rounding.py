from __future__ import annotations


def round_step(value: float, step: float) -> float:
    if step <= 0:
        return value
    return round(round(value / step) * step, 8)


def round_price(value: float, tick_size: float = 0.01) -> float:
    tick = float(tick_size) if float(tick_size) > 0 else 0.01
    return round(round(float(value) / tick) * tick, 8)


def format_price(value: float, decimals: int = 2) -> str:
    """Format a price for logs / Telegram using a fixed decimal count (from coin ``price_rounding_decimal``)."""
    d = max(0, min(16, int(decimals)))
    r = round(float(value), d)
    return f"{r:.{d}f}"


def round_qty(value: float, decimals: int = 6) -> float:
    return round(float(value), int(decimals))


def round_usd(value: float, decimals: int = 2) -> float:
    return round(float(value), int(decimals))


def round_ratio(value: float, decimals: int = 2) -> float:
    return round(float(value), int(decimals))
