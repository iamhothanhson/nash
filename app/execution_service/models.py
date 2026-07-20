from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    status: str
    symbol: str | None = None
    direction: str | None = None
    position_side: str | None = None
    entry_order_id: int | str | None = None
    entry_price: float | None = None
    filled_qty: float | None = None
    stop_loss_order_id: int | str | None = None
    tp1_order_id: int | str | None = None
    reason: str | None = None
    mode: str | None = None
    raw: dict[str, Any] | None = None
