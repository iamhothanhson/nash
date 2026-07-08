from __future__ import annotations

from .order_planner import OrderPlanner, risk_controls_allow


def build_order_plan(*args, **kwargs):
    return OrderPlanner.build_order_plan(*args, **kwargs)

try:
    from risk.risk_multiplier_manager import compute_regime_risk_multiplier
except ImportError:
    def compute_regime_risk_multiplier(*args, **kwargs) -> float:  # type: ignore[misc]
        return 1.0

__all__ = ["OrderPlanner", "build_order_plan", "risk_controls_allow", "compute_regime_risk_multiplier"]
