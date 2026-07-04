"""
Canonical strategy-selection models (strategy-agnostic).

Strategy implementations continue returning their own ``TradeSignal`` types; adapters
here lift them into :class:`StrategyCandidate` for scoring and arbitration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

import pandas as pd

StrategyFamily = Literal["trend_following", "liquidity"]
SelectorMode = Literal["winner_takes_all", "weighted_scores"]


@dataclass(frozen=True)
class TrendRegimeComponents:
    """Normalized component scores in ``[0, 1]`` for auditability."""

    adx_strength: float
    ema_slope_quality: float
    breakout_expansion: float
    htf_structure: float
    volatility_expansion: float
    directional_persistence: float


@dataclass(frozen=True)
class TrendRegimeReport:
    """Full trend regime evaluation (trend strategy only; no reversal regime)."""

    allows_trend_strategy: bool
    trend_strength: float
    """Aggregate strength in ``[0, 1]``."""
    primary_reason: str
    components: TrendRegimeComponents
    metadata: dict[str, Any] = field(default_factory=dict)
    """Raw diagnostics (ADX value, EMA distances, ATR ratios, etc.)."""


@dataclass(frozen=True)
class ScoreBreakdown:
    """Interpretable multiplicative-style decomposition (see scoring engine)."""

    expected_edge: float
    confidence: float
    trend_regime_factor: float
    volatility_quality: float
    liquidity_quality: float
    composite: float
    notes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyCandidate:
    """Unified signal view for the selector (built from a native strategy signal)."""

    strategy_family: StrategyFamily
    setup_type: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: float
    r_multiple: float
    confidence: float
    timestamp: datetime
    native_signal: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RankedCandidate:
    candidate: StrategyCandidate
    breakdown: ScoreBreakdown


@dataclass(frozen=True)
class StrategySelectionResult:
    """Outcome of arbitration + observability payload."""

    symbol: str
    mode: SelectorMode
    regime: TrendRegimeReport
    ranked: tuple[RankedCandidate, ...]
    winner: RankedCandidate | None
    execution_signal: Any | None
    """Original native ``TradeSignal`` to preserve execution compatibility."""
    reject_reason: str | None
    family_weights: dict[str, float]
    """Normalized weights by strategy family (``weighted_scores`` mode); execution still single-winner unless portfolio consumes weights."""
    debug: dict[str, Any] = field(default_factory=dict)


def infer_bar_timestamp(data_5m: pd.DataFrame | None) -> datetime:
    if data_5m is not None and len(data_5m.index) > 0:
        ts = data_5m.index[-1]
        if isinstance(ts, pd.Timestamp):
            if ts.tzinfo is None:
                return ts.tz_localize(timezone.utc).to_pydatetime()
            return ts.to_pydatetime()
    return datetime.now(timezone.utc)


def native_to_candidate(
    native: Any,
    *,
    strategy_family: StrategyFamily,
    data_5m: pd.DataFrame | None,
    extra_meta: dict[str, Any] | None = None,
) -> StrategyCandidate | None:
    """Lift a strategy ``TradeSignal`` into :class:`StrategyCandidate` without importing strategy modules."""
    if native is None:
        return None
    meta: dict[str, Any] = dict(extra_meta or {})
    meta.setdefault("setup_grade", getattr(native, "setup_grade", None))
    meta.setdefault("setup_score", getattr(native, "setup_score", None))
    meta.setdefault("confirmation_mode", getattr(native, "confirmation_mode", None))
    meta.setdefault("rsi", getattr(native, "rsi", None))
    meta.setdefault("volatility", getattr(native, "volatility", None))
    meta.setdefault("atr", getattr(native, "atr", None))
    meta.setdefault("ema_slope", getattr(native, "ema_slope", None))

    tp = float(getattr(native, "tp1", 0.0))
    conf = _confidence_from_native(native)

    return StrategyCandidate(
        strategy_family=strategy_family,
        setup_type=str(getattr(native, "setup_type", "")),
        direction=str(getattr(native, "direction", "")),
        entry=float(getattr(native, "entry", 0.0)),
        stop_loss=float(getattr(native, "stop_loss", 0.0)),
        take_profit=tp,
        r_multiple=float(getattr(native, "r_multiple", 0.0)),
        confidence=conf,
        timestamp=infer_bar_timestamp(data_5m),
        native_signal=native,
        metadata=meta,
    )


def _confidence_from_native(native: Any) -> float:
    grade = str(getattr(native, "setup_grade", "A"))
    base = 0.72 if grade == "A" else 0.88 if grade == "A+" else 0.60
    score = getattr(native, "setup_score", None)
    if score is None:
        return base
    try:
        s = int(score)
    except (TypeError, ValueError):
        return base
    bump = min(0.12, max(0.0, (s - 6) * 0.02))
    return max(0.35, min(1.0, base + bump))
