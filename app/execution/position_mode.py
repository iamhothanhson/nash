"""Binance USDT-M position mode (one-way vs hedge) helpers."""

from __future__ import annotations

import re

_VALID_MODES = frozenset({"auto", "hedge", "oneway"})


def normalize_position_mode_setting(raw: str) -> str:
    """
    Resolve ``BINANCE_POSITION_MODE``: ``auto`` | ``hedge`` | ``oneway``.

    Accepts aliases (``dual``, ``one-way``, ``false``, …) and ignores comment-like
    tails such as ``hedge | oneway | auto`` (uses the first recognized token).
    """
    v = str(raw or "auto").strip().lower()
    if not v:
        return "auto"

    direct = _map_mode_token(v)
    if direct is not None:
        return direct

    for token in re.split(r"[\s|,/]+", v):
        mapped = _map_mode_token(token.strip())
        if mapped is not None:
            return mapped
    return "auto"


def _map_mode_token(token: str) -> str | None:
    if not token:
        return None
    if token in ("hedge", "dual", "dual_side", "dualside", "true", "1"):
        return "hedge"
    if token in ("oneway", "one_way", "one-way", "single", "false", "0"):
        return "oneway"
    if token == "auto":
        return "auto"
    return None


def describe_position_mode(mode: str, *, hedge_active: bool | None = None) -> str:
    """Human-readable mode for startup logs."""
    m = normalize_position_mode_setting(mode)
    if m == "auto":
        if hedge_active is None:
            return "auto (query exchange on first order)"
        return f"auto → {'hedge' if hedge_active else 'oneway'} (from exchange)"
    if m == "hedge":
        return "hedge (positionSide LONG/SHORT on orders)"
    return "oneway (no positionSide; one-way / BOTH)"


def position_side_for_entry(order_side: str) -> str:
    """Hedge leg for opening: BUY -> LONG, SELL -> SHORT."""
    return "LONG" if str(order_side).strip().upper() == "BUY" else "SHORT"


def position_side_for_reduce_order(protective_order_side: str) -> str:
    """Hedge leg for reduce-only close: SELL closes LONG, BUY closes SHORT."""
    return "LONG" if str(protective_order_side).strip().upper() == "SELL" else "SHORT"


def position_side_for_direction(direction: str) -> str:
    return "LONG" if str(direction).strip().upper() == "LONG" else "SHORT"
