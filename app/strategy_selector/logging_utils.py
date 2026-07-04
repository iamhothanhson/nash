"""Structured selector logging for production dashboards and log aggregation."""

from __future__ import annotations

import json
import logging
from typing import Any

from strategy_selector.models import StrategySelectionResult

logger = logging.getLogger(__name__)


def selection_to_log_dict(result: StrategySelectionResult) -> dict[str, Any]:
    r = result.regime
    return {
        "symbol": result.symbol,
        "mode": result.mode,
        "reject_reason": result.reject_reason,
        "winner_family": result.winner.candidate.strategy_family if result.winner else None,
        "winner_composite": result.winner.breakdown.composite if result.winner else None,
        "family_weights": result.family_weights,
        "trend_regime": {
            "allows_trend_strategy": r.allows_trend_strategy,
            "trend_strength": round(r.trend_strength, 4),
            "primary_reason": r.primary_reason,
            "components": {
                "adx_strength": round(r.components.adx_strength, 4),
                "ema_slope_quality": round(r.components.ema_slope_quality, 4),
                "breakout_expansion": round(r.components.breakout_expansion, 4),
                "htf_structure": round(r.components.htf_structure, 4),
                "volatility_expansion": round(r.components.volatility_expansion, 4),
                "directional_persistence": round(r.components.directional_persistence, 4),
            },
            "metadata_keys": list(r.metadata.keys()),
        },
        "ranked": [
            {
                "family": x.candidate.strategy_family,
                "setup_type": x.candidate.setup_type,
                "composite": round(x.breakdown.composite, 6),
            }
            for x in result.ranked
        ],
        "debug": result.debug,
    }


def log_selection_json(result: StrategySelectionResult, *, level: int = logging.INFO) -> None:
    payload = selection_to_log_dict(result)
    logger.log(level, "strategy_selector %s", json.dumps(payload, default=str))


def format_selection_human(result: StrategySelectionResult) -> str:
    lines = [
        f"[StrategySelector] symbol={result.symbol} mode={result.mode}",
        f"  trend_regime: strength={result.regime.trend_strength:.3f} "
        f"allows_trend={result.regime.allows_trend_strategy} reason={result.regime.primary_reason}",
        f"  family_weights: {result.family_weights}",
    ]
    if result.reject_reason:
        lines.append(f"  REJECT: {result.reject_reason}")
    if result.winner:
        w = result.winner
        lines.append(
            f"  WINNER: {w.candidate.strategy_family} | {w.candidate.setup_type} | "
            f"score={w.breakdown.composite:.4f}"
        )
        b = w.breakdown
        lines.append(
            f"    breakdown: edge={b.expected_edge:.3f} conf={b.confidence:.3f} "
            f"regime_f={b.trend_regime_factor:.3f} vol_q={b.volatility_quality:.3f} liq_q={b.liquidity_quality:.3f}"
        )
    for row in result.debug.get("candidates", []):
        if isinstance(row, dict) and row.get("status") == "blocked_by_trend_regime":
            lines.append(f"  blocked: trend_following | regime={row.get('regime_reason')}")
    return "\n".join(lines)
