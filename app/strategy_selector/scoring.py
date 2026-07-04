"""
Adaptive, interpretable scoring for strategy arbitration.

Composite is built from named factors with configurable clamps — no opaque breakout×3.5-style knobs.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

try:
    from strategy.trend_following.trend_following_config import (
        SELECTOR_REVERSAL_TREND_HEADWIND,
        SELECTOR_TREND_GATE_SOFTNESS,
    )
except ImportError:  # pragma: no cover - fallback to actual module path
    from strategy.trend_following.config import (
        SELECTOR_REVERSAL_TREND_HEADWIND,
        SELECTOR_TREND_GATE_SOFTNESS,
    )
from strategy_selector.models import (
    ScoreBreakdown,
    StrategyCandidate,
    StrategyFamily,
    TrendRegimeReport,
)


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))


def expected_reward_risk(candidate: StrategyCandidate) -> float:
    """Proxy for edge using TP1 vs stop distance (capped)."""
    risk = abs(candidate.entry - candidate.stop_loss)
    reward = abs(candidate.take_profit - candidate.entry)
    if risk <= 0 or candidate.entry <= 0:
        return 0.35
    rr = reward / risk
    cap = 4.0
    return _clamp01(rr / cap)


def volatility_quality_from_series(data_15m: pd.DataFrame | None, sig_vol: float | None) -> float:
    """Moderate expansion preferred — penalize dead & chaotic extremes via ATR percentile proxy."""
    if data_15m is None or len(data_15m) < 40 or "close" not in data_15m.columns:
        return _clamp01(0.55 + 0.45 * _clamp01((sig_vol or 0.004) / 0.012)) if sig_vol else 0.55

    from indicators import calculate_atr

    close = data_15m["close"].astype(float)
    atr = calculate_atr(data_15m, 14)
    atr_last = float(atr.iloc[-1])
    med = float(atr.iloc[-48:].median()) if len(atr) >= 48 else float(atr.iloc[-1])
    ratio = atr_last / max(med, 1e-12)
    # Target band ~0.95–1.25
    if ratio < 0.85:
        q = _clamp01((ratio - 0.65) / 0.25)
    elif ratio > 1.45:
        q = _clamp01((1.65 - ratio) / 0.35)
    else:
        q = _clamp01((ratio - 0.85) / 0.60)
    return max(0.25, min(1.0, q))


def liquidity_quality_from_series(data_5m: pd.DataFrame | None) -> float:
    """Relative volume vs recent mean on 5m (surrogate for execution quality)."""
    if data_5m is None or len(data_5m) < 15 or "volume" not in data_5m.columns:
        return 0.70
    v = data_5m["volume"].astype(float)
    last = float(v.iloc[-1])
    vm = float(v.iloc[-20:].mean())
    if vm <= 0:
        return 0.65
    r = last / vm
    return _clamp01(0.45 + 0.55 * _clamp01((r - 0.45) / 1.15))


def score_candidate(
    candidate: StrategyCandidate,
    *,
    family: StrategyFamily,
    regime: TrendRegimeReport,
    data_15m: pd.DataFrame | None,
    data_5m: pd.DataFrame | None,
) -> ScoreBreakdown:
    """
    Adaptive composite score.

    - Trend-following: regime strength multiplicatively boosts score when aligned.
    - Liquidity reversal: independent of reversal regime detector; mild structural scaling only from signal metadata.
    """
    from config import settings

    edge = expected_reward_risk(candidate)
    conf = _clamp01(candidate.confidence)

    sig_vol = candidate.metadata.get("volatility")
    if isinstance(sig_vol, (int, float)):
        vq = volatility_quality_from_series(data_15m, float(sig_vol))
    else:
        vq = volatility_quality_from_series(data_15m, None)

    lq = liquidity_quality_from_series(data_5m)

    notes: dict[str, Any] = {"family": family}

    if family == "trend_following":
        tr = float(regime.trend_strength)
        # If hard gate failed, soften factor so ranked trend scores fall below reversal alternatives.
        gate_ok = regime.allows_trend_strategy
        regime_factor = tr if gate_ok else tr * float(SELECTOR_TREND_GATE_SOFTNESS)
        notes["trend_gate_ok"] = gate_ok
    else:
        # Reversal: does not use trend *regime classification* — only optional mild crowding term from same numeric strength.
        headwind = float(SELECTOR_REVERSAL_TREND_HEADWIND)
        regime_factor = max(0.2, 1.0 - headwind * float(regime.trend_strength))
        notes["reversal_trend_headwind_applied"] = headwind > 0.0

    raw = edge * conf * regime_factor * vq * lq
    floor = float(getattr(settings, "SELECTOR_SCORE_FLOOR", 0.05))
    composite = max(floor, float(raw))

    return ScoreBreakdown(
        expected_edge=edge,
        confidence=conf,
        trend_regime_factor=float(regime_factor),
        volatility_quality=vq,
        liquidity_quality=lq,
        composite=composite,
        notes=notes,
    )
