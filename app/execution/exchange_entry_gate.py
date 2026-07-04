"""Live/demo pre-entry checks vs exchange position size and per-symbol caps."""

from __future__ import annotations

from typing import Any

from coins.loader import max_opened_positions_for
from execution.position_mode import position_side_for_direction, position_side_for_entry


def _entry_leg_has_exchange_size(client: Any, symbol: str, *, direction: str | None, side: str | None) -> bool:
    sym_u = str(symbol).strip().upper()
    if bool(client.use_hedge_position_side()):
        leg = None
        if direction:
            leg = position_side_for_direction(direction)
        elif side:
            leg = position_side_for_entry(str(side).strip().upper())
        if leg:
            return abs(float(client.get_position_amount(sym_u, leg))) > 1e-10
    return bool(client.has_open_position_size(sym_u))


def should_block_exchange_entry(
    client: Any,
    symbol: str,
    positions_per_symbol: dict[str, int],
    *,
    direction: str | None = None,
    side: str | None = None,
) -> tuple[bool, str]:
    """
    Whether to skip a new entry on the exchange.

    - Under ``max_opened_positions``: allow even if the exchange already has size (stack in).
    - At cap: block.
    - Bot tracks zero but exchange has size: block (orphan / reconcile first).
    """
    sym_u = str(symbol).strip().upper()
    tracked = int(positions_per_symbol.get(sym_u, 0))
    cap = max_opened_positions_for(sym_u)
    if tracked >= cap:
        return True, f"per-symbol cap ({tracked} open, max {cap})"
    if tracked > 0:
        return False, ""
    try:
        if _entry_leg_has_exchange_size(client, sym_u, direction=direction, side=side):
            summary = str(client.open_position_summary(sym_u))
            return True, f"untracked exchange position ({summary})"
    except Exception as exc:
        return True, f"exchange position check failed ({exc})"
    return False, ""
