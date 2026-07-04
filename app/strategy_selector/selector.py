"""Strategy arbitration: winner-takes-all vs weighted score allocation."""

from __future__ import annotations

from typing import Any

import pandas as pd

from strategy_selector.context import set_last_selection
from strategy_selector.models import (
    RankedCandidate,
    SelectorMode,
    StrategyCandidate,
    StrategySelectionResult,
    TrendRegimeReport,
    native_to_candidate,
)
from strategy_selector.scoring import score_candidate

try:
    from strategy.trend_following.trend_following_config import (
        SELECTOR_DYNAMIC_MIN_SCORE_STRONG_TREND,
        SELECTOR_TREND_MIN_STRENGTH_EPS,
        SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE,
        TREND_REQUIRE_REGIME_DIRECTION_MATCH,
    )
except ImportError:  # pragma: no cover - fallback to actual module path
    from strategy.trend_following.config import (
        SELECTOR_DYNAMIC_MIN_SCORE_STRONG_TREND,
        SELECTOR_TREND_MIN_STRENGTH_EPS,
        SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE,
        TREND_REQUIRE_REGIME_DIRECTION_MATCH,
    )


class StrategySelector:
    """
    Orchestrates trend regime detection → candidate scoring → arbitration.

    Liquidity sweep reversal strategy internals are unchanged; only native signals are consumed here.
    """

    def __init__(self, regime_detector: Any | None = None) -> None:
        # Lazy import avoids circular init: market_regime.trend_regime_detector → strategy_selector.models
        if regime_detector is None:
            from strategy.market_regime.trend_regime_detector import ProductionTrendRegimeDetector

            regime_detector = ProductionTrendRegimeDetector()
        self._regime = regime_detector

    def select(
        self,
        *,
        symbol: str,
        data_1h: pd.DataFrame,
        data_15m: pd.DataFrame,
        data_5m: pd.DataFrame,
        reversal_signal: Any | None,
        trend_signal: Any | None,
        enable_trend: bool,
        trend_regime_filter: bool,
        mode: SelectorMode,
        min_score: float,
    ) -> StrategySelectionResult:
        regime = self._regime.evaluate(data_1h, data_15m)
        ranked, debug_candidates = self._collect_candidates(
            regime=regime,
            data_15m=data_15m,
            data_5m=data_5m,
            reversal_signal=reversal_signal,
            trend_signal=trend_signal,
            enable_trend=enable_trend,
            trend_regime_filter=trend_regime_filter,
        )
        family_weights = self._family_weights(ranked, mode)
        effective_min_score = self._effective_min_score(min_score, data_5m, regime)
        winner, exec_sig, reject_reason = self._pick_winner(ranked, effective_min_score)

        result = StrategySelectionResult(
            symbol=symbol,
            mode=mode,
            regime=regime,
            ranked=ranked,
            winner=winner,
            execution_signal=exec_sig,
            reject_reason=reject_reason,
            family_weights=family_weights,
            debug={
                "candidates": debug_candidates,
                "min_score": min_score,
                "effective_min_score": effective_min_score,
                "selector_version": "1.0.0",
                "settings_ref": {
                    "enable_trend": enable_trend,
                    "trend_regime_filter": trend_regime_filter,
                },
            },
        )
        set_last_selection(result)
        return result

    def _collect_candidates(
        self,
        *,
        regime: TrendRegimeReport,
        data_15m: pd.DataFrame,
        data_5m: pd.DataFrame,
        reversal_signal: Any | None,
        trend_signal: Any | None,
        enable_trend: bool,
        trend_regime_filter: bool,
    ) -> tuple[tuple[RankedCandidate, ...], list[dict[str, Any]]]:
        ranked_list: list[RankedCandidate] = []
        debug_candidates: list[dict[str, Any]] = []

        if reversal_signal is not None:
            ranked = self._build_ranked_candidate(
                native_signal=reversal_signal,
                family="liquidity",
                source="liquidity_sweep_reversal",
                regime=regime,
                data_15m=data_15m,
                data_5m=data_5m,
            )
            if ranked is not None:
                ranked_list.append(ranked)
                debug_candidates.append(
                    self._debug_rank_row("liquidity", ranked.candidate, ranked.breakdown, regime)
                )

        include_trend, trend_block = self._should_include_trend(
            trend_signal=trend_signal,
            regime=regime,
            enable_trend=enable_trend,
            trend_regime_filter=trend_regime_filter,
        )
        if trend_block is not None:
            debug_candidates.append(trend_block)
        if include_trend and trend_signal is not None:
            ranked = self._build_ranked_candidate(
                native_signal=trend_signal,
                family="trend_following",
                source="trend_following",
                regime=regime,
                data_15m=data_15m,
                data_5m=data_5m,
            )
            if ranked is not None:
                ranked_list.append(ranked)
                debug_candidates.append(
                    self._debug_rank_row("trend_following", ranked.candidate, ranked.breakdown, regime)
                )

        ranked = tuple(sorted(ranked_list, key=lambda r: r.breakdown.composite, reverse=True))
        return ranked, debug_candidates

    def _build_ranked_candidate(
        self,
        *,
        native_signal: Any,
        family: str,
        source: str,
        regime: TrendRegimeReport,
        data_15m: pd.DataFrame,
        data_5m: pd.DataFrame,
    ) -> RankedCandidate | None:
        c = native_to_candidate(
            native_signal,
            strategy_family=family,
            data_5m=data_5m,
            extra_meta={"source": source},
        )
        if c is None:
            return None
        bd = score_candidate(
            c,
            family=family,  # type: ignore[arg-type]
            regime=regime,
            data_15m=data_15m,
            data_5m=data_5m,
        )
        return RankedCandidate(candidate=c, breakdown=bd)

    def _should_include_trend(
        self,
        *,
        trend_signal: Any | None,
        regime: TrendRegimeReport,
        enable_trend: bool,
        trend_regime_filter: bool,
    ) -> tuple[bool, dict[str, Any] | None]:
        if not enable_trend or trend_signal is None:
            return False, None

        gated_out = bool(trend_regime_filter) and not regime.allows_trend_strategy
        if gated_out:
            return False, self._blocked_row(
                status="blocked_by_trend_regime",
                regime=regime,
                extra={"regime_reason": regime.primary_reason},
            )

        trend_strength_min = float(SELECTOR_TREND_MIN_STRENGTH_TO_COMPETE)
        strength_eps = max(0.0, float(SELECTOR_TREND_MIN_STRENGTH_EPS))
        effective_min = trend_strength_min - strength_eps
        if float(regime.trend_strength) < effective_min:
            return False, self._blocked_row(
                status="blocked_by_trend_strength",
                regime=regime,
                extra={"min_required": trend_strength_min, "min_effective": effective_min},
            )

        regime_direction = self._regime_direction(regime)
        trend_direction = str(getattr(trend_signal, "direction", "")).upper()
        require_dir_match = bool(TREND_REQUIRE_REGIME_DIRECTION_MATCH)
        mismatch_direction = (
            require_dir_match
            and regime_direction in ("LONG", "SHORT")
            and trend_direction in ("LONG", "SHORT")
            and trend_direction != regime_direction
        )
        if mismatch_direction:
            return False, self._blocked_row(
                status="blocked_by_regime_direction_mismatch",
                regime=regime,
                extra={"trend_direction": trend_direction, "regime_direction": regime_direction},
            )
        return True, None

    def _blocked_row(
        self,
        *,
        status: str,
        regime: TrendRegimeReport,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row: dict[str, Any] = {
            "family": "trend_following",
            "status": status,
            "trend_strength": float(regime.trend_strength),
            "regime_reason": str(regime.primary_reason),
        }
        if extra:
            row.update(extra)
        return row

    def _effective_min_score(
        self,
        min_score: float,
        data_5m: pd.DataFrame,
        regime: TrendRegimeReport,
    ) -> float:
        from config import settings

        ms = float(min_score)
        if not bool(getattr(settings, "SELECTOR_DYNAMIC_MIN_SCORE", True)):
            return ms
        try:
            vol = data_5m["volume"].astype(float)
            vr = float(vol.iloc[-1]) / max(float(vol.iloc[-20:].mean()), 1e-12)
        except Exception:
            vr = 1.0
        if vr < float(getattr(settings, "SELECTOR_DYNAMIC_MIN_SCORE_VOL_LOW", 0.70)):
            ms += float(getattr(settings, "SELECTOR_DYNAMIC_MIN_SCORE_ADD", 0.02))
        if float(regime.trend_strength) > float(SELECTOR_DYNAMIC_MIN_SCORE_STRONG_TREND):
            ms -= float(getattr(settings, "SELECTOR_DYNAMIC_MIN_SCORE_SUB", 0.01))
        ms = max(float(getattr(settings, "SELECTOR_SCORE_FLOOR", 0.05)), ms)
        ms = min(float(getattr(settings, "SELECTOR_DYNAMIC_MIN_SCORE_MAX", 0.20)), ms)
        return float(ms)

    def _family_weights(
        self,
        ranked: tuple[RankedCandidate, ...],
        mode: SelectorMode,
    ) -> dict[str, float]:
        if not ranked:
            return {}
        scores = {r.candidate.strategy_family: r.breakdown.composite for r in ranked}
        if mode == "winner_takes_all":
            top = ranked[0].candidate.strategy_family
            return {k: (1.0 if k == top else 0.0) for k in scores}
        total = sum(max(s, 1e-12) for s in scores.values())
        return {k: max(0.0, v / total) for k, v in scores.items()}

    def _pick_winner(
        self,
        ranked: tuple[RankedCandidate, ...],
        min_score: float,
    ) -> tuple[RankedCandidate | None, Any | None, str | None]:
        from config import settings

        if not ranked:
            return None, None, "no_candidates"
        best = ranked[0]
        if len(ranked) >= 2:
            min_gap = max(0.0, float(getattr(settings, "SELECTOR_MIN_WINNER_GAP", 0.015)))
            gap = float(best.breakdown.composite) - float(ranked[1].breakdown.composite)
            if gap < min_gap:
                return None, None, f"winner_gap_too_small<{min_gap:.4f}"
        # Suppress low-quality trades only when two families compete; a single active
        # strategy (e.g. liquidity-only with trend disabled) should match legacy "return rev".
        if len(ranked) >= 2 and best.breakdown.composite < min_score:
            return None, None, f"below_min_score<{min_score:.4f}"
        return best, best.candidate.native_signal, None

    def _regime_direction(self, regime: TrendRegimeReport) -> str | None:
        meta = regime.metadata if isinstance(regime.metadata, dict) else {}
        htf = meta.get("htf_structure_detail") if isinstance(meta.get("htf_structure_detail"), dict) else {}
        if bool(htf.get("bull_stack", False)) and not bool(htf.get("bear_stack", False)):
            return "LONG"
        if bool(htf.get("bear_stack", False)) and not bool(htf.get("bull_stack", False)):
            return "SHORT"
        slope = float(meta.get("ema_slope_raw", 0.0) or 0.0)
        if slope > 0:
            return "LONG"
        if slope < 0:
            return "SHORT"
        return None

    def _debug_rank_row(
        self,
        label: str,
        c: StrategyCandidate,
        bd: Any,
        regime: TrendRegimeReport,
    ) -> dict[str, Any]:
        return {
            "family": label,
            "setup_type": c.setup_type,
            "direction": c.direction,
            "composite": round(bd.composite, 6),
            "expected_edge": round(bd.expected_edge, 4),
            "confidence": round(bd.confidence, 4),
            "trend_regime_factor": round(bd.trend_regime_factor, 4),
            "volatility_quality": round(bd.volatility_quality, 4),
            "liquidity_quality": round(bd.liquidity_quality, 4),
            "regime_trend_strength": round(regime.trend_strength, 4),
            "regime_allows_trend": regime.allows_trend_strategy,
        }
