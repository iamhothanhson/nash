from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

def compute_strength(grade):
    if grade == "A+":
        return 2
    elif grade == "A":
        return 1
    return 0

def compute_weights(strength_scores: dict[str, float]) -> dict[str, float]:
    n = len(strength_scores)
    if n == 0:
        return {}

    return {k: 1 / n for k in strength_scores}


def get_allocations(
    total_capital: float,
    weights: dict[str, float],
) -> dict[str, float]:
    return {
        sym: total_capital * w
        for sym, w in weights.items()
    }


def normalize_positive_weights(raw: dict[str, float]) -> dict[str, float]:
    """Normalize non-negative weights to sum to 1.0 (strategy-family or symbol buckets)."""
    pos = {k: max(0.0, float(v)) for k, v in raw.items()}
    s = sum(pos.values())
    if s <= 0.0:
        return {}
    return {k: v / s for k, v in pos.items()}

def log_allocation(weights: dict[str, float], allocations: dict[str, float]) -> None:
    print("\n=== Allocation ===")
    for sym in weights:
        print(f"{sym}: weight={weights[sym]:.2f}, allocation={allocations[sym]:.2f}")
    print(f"Total allocation: {sum(allocations.values()):.2f}")