from __future__ import annotations

from .order_planner import OrderPlanner


def build_order_plan(*args, **kwargs):
    return OrderPlanner.build_order_plan(*args, **kwargs)

__all__ = ["OrderPlanner", "build_order_plan", "risk_controls_allow"]
