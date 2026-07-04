"""Request-scoped selector decisions for observability without changing call signatures."""

from __future__ import annotations

from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from strategy_selector.models import StrategySelectionResult

_last_selection: ContextVar["StrategySelectionResult | None"] = ContextVar(
    "strategy_selector_last", default=None
)


def set_last_selection(result: "StrategySelectionResult | None") -> None:
    _last_selection.set(result)


def get_last_selection() -> "StrategySelectionResult | None":
    return _last_selection.get()
