from __future__ import annotations

from dataclasses import asdict

from app.core.constants import BREAKOUT
from app.strategy.trend_following.breakout.types import BreakoutPipelineStats
from core.enums import RejectReason, RejectionStage
from core.types import RejectionMetric
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import (
    BREAKOUT_LONG_HARD,
    BREAKOUT_LONG_SOFT,
    BREAKOUT_SHORT_HARD,
    BREAKOUT_SHORT_SOFT,
)
from strategy.trend_following.breakout.feature_builder import FeatureBuilder
from .rejection import BreakoutRejectionAnalyzer

EPSILON = 1e-9


class BreakoutDetector:

    def __init__(self):
        self.reject_stats = None
        self.breakout_rejection = BreakoutRejectionAnalyzer()
        self.pipeline_stats = BreakoutPipelineStats()

    def detect(self, market_state):
        self._current_ts = getattr(market_state, "timestamp", None)
        self._current_symbol = getattr(market_state, "symbol", None)
        breakout_feature = FeatureBuilder.compute_breakout_features(
            market_state.data_15m, market_state.indicators
        )

        self.pipeline_stats.candidates += 1

        if breakout_feature.direction == "LONG":
            self.pipeline_stats.long_candidates += 1
            if not self.hard_check_long(breakout_feature, market_state.indicators):
                return None
            self.pipeline_stats.hard_pass += 1
            if not self.soft_check_long(breakout_feature, market_state.indicators):
                return None
            self.pipeline_stats.soft_pass += 1
            self.pipeline_stats.setup_candidates += 1
            return SetupCandidate(
                setup_type=BREAKOUT,
                direction="LONG",
                trigger_type="breakout",
                anchor=breakout_feature.breakout_level,
                features=asdict(breakout_feature),
                detected_at=market_state.timestamp,
                timeframe=market_state.timeframe,
            )

        elif breakout_feature.direction == "SHORT":
            self.pipeline_stats.short_candidates += 1
            if not self.hard_check_short(breakout_feature, market_state.indicators):
                return None
            self.pipeline_stats.hard_pass += 1
            if not self.soft_check_short(breakout_feature, market_state.indicators):
                return None
            self.pipeline_stats.soft_pass += 1
            self.pipeline_stats.setup_candidates += 1
            return SetupCandidate(
                setup_type=BREAKOUT,
                direction="SHORT",
                trigger_type="breakout",
                anchor=breakout_feature.breakout_level,
                features=asdict(breakout_feature),
                detected_at=market_state.timestamp,
                timeframe=market_state.timeframe,
            )

        return None

    def hard_check_long(self, features, indicators):
        hard = BREAKOUT_LONG_HARD
        reasons = []
        metrics = []

        if features.close_above_level != hard["close_above_recent_high"]:
            reasons.append("no_close_above_high")
            metrics.append(RejectionMetric("close_above_level", float(features.close_above_level), float(hard["close_above_recent_high"])))

        if features.breakout_strength < hard["min_strength"] - EPSILON:
            reasons.append(f"weak_strength {features.breakout_strength:.4f}")
            metrics.append(RejectionMetric("breakout_strength", features.breakout_strength, hard["min_strength"]))

        if hard["require_ema_alignment"] and not features.htf_confirmed:
            reasons.append("ema_alignment")
            metrics.append(RejectionMetric("htf_confirmed", float(features.htf_confirmed), float(hard["require_ema_alignment"])))

        adx15 = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0
        adx1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0

        if adx15 < hard["min_adx"] - EPSILON:
            reasons.append(f"weak_adx_15m {adx15:.1f}")
            metrics.append(RejectionMetric("adx_15m", adx15, hard["min_adx"]))
        if adx1h < hard["min_adx_1h"] - EPSILON:
            reasons.append(f"weak_adx_1h {adx1h:.1f}")
            metrics.append(RejectionMetric("adx_1h", adx1h, hard["min_adx_1h"]))

        if reasons:
            self._reject(RejectionStage.HARD_LONG, reasons, metrics)
            return False

        return True

    def soft_check_long(self, features, indicators):
        soft = BREAKOUT_LONG_SOFT
        reasons = []
        metrics = []

        if indicators.volume_ratio < soft["min_volume_ratio"] - EPSILON:
            reasons.append(f"low_volume {indicators.volume_ratio:.2f}")
            metrics.append(RejectionMetric("volume_ratio", indicators.volume_ratio, soft["min_volume_ratio"]))

        if indicators.ema20_slope_15m < soft["min_ema_slope"] - EPSILON:
            reasons.append(f"weak_ema_slope {indicators.ema20_slope_15m:.5f}")
            metrics.append(RejectionMetric("ema_slope", indicators.ema20_slope_15m, soft["min_ema_slope"]))

        if indicators.rsi < soft["min_rsi"] - EPSILON:
            reasons.append(f"weak_rsi {indicators.rsi:.1f}")
            metrics.append(RejectionMetric("rsi", indicators.rsi, soft["min_rsi"]))

        if features.candle_body_ratio < soft["min_body_ratio"] - EPSILON:
            reasons.append(f"small_body {features.candle_body_ratio:.2f}")
            metrics.append(RejectionMetric("candle_body_ratio", features.candle_body_ratio, soft["min_body_ratio"]))

        if features.distance_from_level_pct > soft["max_close_to_high_pct"] + EPSILON:
            reasons.append(f"poor_close_location {features.distance_from_level_pct:.3f}")
            metrics.append(RejectionMetric("distance_from_level_pct", features.distance_from_level_pct, soft["max_close_to_high_pct"]))

        passed_soft = 5 - len(reasons)

        if passed_soft < 3:
            self._reject(RejectionStage.SOFT_LONG, reasons, metrics)
            return False

        return True

    def hard_check_short(self, features, indicators):
        hard = BREAKOUT_SHORT_HARD
        reasons = []
        metrics = []

        if features.close_above_level:
            reasons.append("no_close_below_low")
            metrics.append(RejectionMetric("close_below_level", float(not features.close_above_level), 1.0))

        if features.breakout_strength < hard["min_strength"] - EPSILON:
            reasons.append(f"weak_strength {features.breakout_strength:.4f}")
            metrics.append(RejectionMetric("breakout_strength", features.breakout_strength, hard["min_strength"]))

        if hard["require_ema_alignment"] and not features.htf_confirmed:
            reasons.append("ema_alignment")
            metrics.append(RejectionMetric("htf_confirmed", float(features.htf_confirmed), float(hard["require_ema_alignment"])))

        adx15 = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0
        adx1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0

        if adx15 < hard["min_adx"] - EPSILON:
            reasons.append(f"weak_adx_15m {adx15:.1f}")
            metrics.append(RejectionMetric("adx_15m", adx15, hard["min_adx"]))
        if adx1h < hard["min_adx_1h"] - EPSILON:
            reasons.append(f"weak_adx_1h {adx1h:.1f}")
            metrics.append(RejectionMetric("adx_1h", adx1h, hard["min_adx_1h"]))

        if reasons:
            self._reject(RejectionStage.HARD_SHORT, reasons, metrics)
            return False

        return True

    def soft_check_short(self, features, indicators):
        soft = BREAKOUT_SHORT_SOFT
        reasons = []
        metrics = []

        if indicators.volume_ratio < soft["min_volume_ratio"] - EPSILON:
            reasons.append(f"low_volume {indicators.volume_ratio:.2f}")
            metrics.append(RejectionMetric("volume_ratio", indicators.volume_ratio, soft["min_volume_ratio"]))

        if indicators.ema20_slope_15m > soft["max_ema_slope"] + EPSILON:
            reasons.append(f"weak_ema_slope {indicators.ema20_slope_15m:.5f}")
            metrics.append(RejectionMetric("ema_slope", indicators.ema20_slope_15m, soft["max_ema_slope"]))

        if indicators.rsi > soft["max_rsi"] + EPSILON:
            reasons.append(f"weak_rsi {indicators.rsi:.1f}")
            metrics.append(RejectionMetric("rsi", indicators.rsi, soft["max_rsi"]))

        if features.candle_body_ratio < soft["min_body_ratio"] - EPSILON:
            reasons.append(f"small_body {features.candle_body_ratio:.2f}")
            metrics.append(RejectionMetric("candle_body_ratio", features.candle_body_ratio, soft["min_body_ratio"]))

        if features.distance_from_level_pct > soft["max_close_to_low_pct"] + EPSILON:
            reasons.append(f"poor_close_location {features.distance_from_level_pct:.3f}")
            metrics.append(RejectionMetric("distance_from_level_pct", features.distance_from_level_pct, soft["max_close_to_low_pct"]))

        passed_soft = 5 - len(reasons)

        if passed_soft < 3:
            self._reject(RejectionStage.SOFT_SHORT, reasons, metrics)
            return False

        return True

    def _reject(
        self,
        stage: RejectionStage,
        reasons: list[str],
        metrics: list[RejectionMetric],
    ):
        if not reasons:
            return

        reason_map = {
            RejectionStage.HARD_LONG: RejectReason.BREAKOUT_HARD_LONG,
            RejectionStage.HARD_SHORT: RejectReason.BREAKOUT_HARD_SHORT,
            RejectionStage.SOFT_LONG: RejectReason.BREAKOUT_SOFT_LONG,
            RejectionStage.SOFT_SHORT: RejectReason.BREAKOUT_SOFT_SHORT,
        }
        side = stage.value.split("_")[1]

        if self.reject_stats:
            self.reject_stats.reject(reason_map[stage])

        if self.breakout_rejection:
            self.breakout_rejection.add(
                timestamp=self._current_ts,
                symbol=self._current_symbol,
                side=side,
                stage=stage,
                reasons=reasons,
                metrics=metrics,
            )