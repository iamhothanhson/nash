from __future__ import annotations


def apply_execution_cap(
    planned_risk: float,
    max_execution_risk: float,
) -> float:
    return min(float(planned_risk), float(max_execution_risk))


def compute_regime_risk_multiplier(*args, **kwargs) -> float:
    return 1.0


def compute_signal_risk(*args, **kwargs) -> float:
    return 1.0
