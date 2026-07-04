"""
Strategy selection layer: trend regime detection, adaptive scoring, arbitration.

Liquidity sweep reversal strategy modules are not modified; native signals are adapted here.
"""

from strategy_selector.context import get_last_selection, set_last_selection
from strategy_selector.logging_utils import (
    format_selection_human,
    log_selection_json,
    selection_to_log_dict,
)
from strategy_selector.models import (
    RankedCandidate,
    ScoreBreakdown,
    StrategyCandidate,
    StrategySelectionResult,
    TrendRegimeComponents,
    TrendRegimeReport,
    native_to_candidate,
)
from strategy_selector.selector import StrategySelector


def __getattr__(name: str):
    if name == "ProductionTrendRegimeDetector":
        from strategy.market_regime.trend_regime_detector import ProductionTrendRegimeDetector

        return ProductionTrendRegimeDetector
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ProductionTrendRegimeDetector",
    "StrategySelector",
    "StrategyCandidate",
    "StrategySelectionResult",
    "RankedCandidate",
    "ScoreBreakdown",
    "TrendRegimeReport",
    "TrendRegimeComponents",
    "native_to_candidate",
    "get_last_selection",
    "set_last_selection",
    "selection_to_log_dict",
    "format_selection_human",
    "log_selection_json",
]
