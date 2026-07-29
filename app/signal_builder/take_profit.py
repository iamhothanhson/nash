from __future__ import annotations

from typing import Literal


Direction = Literal["LONG", "SHORT"]


def tp_from_r(
    *,
    entry: float,
    stop_loss: float,
    direction: Direction,
    rr: float,
) -> float:
    """
    TP = Entry ± (Risk × RR)
    """

    risk = abs(entry - stop_loss)

    if direction == "LONG":
        return entry + risk * rr

    return entry - risk * rr


def atr_trailing_stop(
    *,
    highest_since_entry: float,
    lowest_since_entry: float,
    atr: float,
    direction: Direction,
    atr_mult: float,
) -> float:
    """
    ATR trailing stop.

    LONG:
        highest_since_entry - ATR × atr_mult

    SHORT:
        lowest_since_entry + ATR × atr_mult
    """

    if direction == "LONG":
        return highest_since_entry - atr * atr_mult

    return lowest_since_entry + atr * atr_mult


def move_to_break_even(
    *,
    entry: float,
    fee_buffer: float = 0.0,
    direction: Direction,
) -> float:
    """
    Break-even stop.

    fee_buffer:
        Fraction of entry (0.001 = 0.1%)
    """

    if direction == "LONG":
        return entry * (1.0 + fee_buffer)

    return entry * (1.0 - fee_buffer)