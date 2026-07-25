from __future__ import annotations

from dataclasses import asdict

from app.core.constants import BREAKOUT
from core.enums import RejectReason, RejectionStage
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import (
    BREAKOUT_LONG_HARD,
    BREAKOUT_LONG_SOFT,
    BREAKOUT_SHORT_HARD,
    BREAKOUT_SHORT_SOFT,
)
from strategy.trend_following.breakout.feature_builder import FeatureBuilder
from .rejection import BreakoutRejectionAnalyzer


class BreakoutDetector:

    def __init__(self):
        self.reject_stats = None
        self.breakout_rejection = BreakoutRejectionAnalyzer()

    def detect(self, market_state):
        self._current_ts = getattr(market_state, "timestamp", None)
        self._current_symbol = getattr(market_state, "symbol", None)
        breakout_feature = FeatureBuilder.compute_breakout_features(
            market_state.data_15m, market_state.indicators
        )

        if breakout_feature.direction == "LONG":
            if not self.hard_check_long(breakout_feature, market_state.indicators):
                return None
            if not self.soft_check_long(breakout_feature, market_state.indicators):
                return None
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
            if not self.hard_check_short(breakout_feature, market_state.indicators):
                return None
            if not self.soft_check_short(breakout_feature, market_state.indicators):
                return None
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

        if features.close_above_level != hard["close_above_recent_high"]:
            reasons.append("no_close_above_high")

        if features.breakout_strength_pct < hard["min_strength"]:
            reasons.append(f"weak_strength {features.breakout_strength_pct:.4f}")

        if hard["require_ema_alignment"] and not features.htf_confirmed:
            reasons.append("ema_alignment")

        adx15 = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0
        adx1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0

        if adx15 < hard["min_adx"] or adx1h < hard["min_adx_1h"]:
            reasons.append(f"weak_adx {adx15:.1f}/{adx1h:.1f}")

        if reasons:
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT_HARD)

            if self.breakout_rejection:
                self.breakout_rejection.add(
                    timestamp=self._current_ts,
                    symbol=self._current_symbol,
                    side="LONG",
                    stage=RejectionStage.HARD,
                    reasons=reasons,
                    features=asdict(features),
                )

            return False

        return True

    def soft_check_long(self, features, indicators):
        soft = BREAKOUT_LONG_SOFT
        reasons = []

        if indicators.volume_ratio < soft["min_volume_ratio"]:
            reasons.append(f"low_volume {indicators.volume_ratio:.2f}")

        if indicators.ema_slope < soft["min_ema_slope"]:
            reasons.append(f"weak_ema_slope {indicators.ema_slope:.5f}")

        if indicators.rsi < soft["min_rsi"]:
            reasons.append(f"weak_rsi {indicators.rsi:.1f}")

        if features.candle_body_ratio < soft["min_body_ratio"]:
            reasons.append(f"small_body {features.candle_body_ratio:.2f}")

        if features.distance_from_level_pct > soft["max_close_to_high_pct"]:
            reasons.append(
                f"poor_close_location {features.distance_from_level_pct:.3f}"
            )

        passed_soft = 5 - len(reasons)

        if passed_soft < 3:
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT_SHORT)

            if self.breakout_rejection:
                self.breakout_rejection.add(
                    timestamp=self._current_ts,
                    symbol=self._current_symbol,
                    side="LONG",
                    stage=RejectionStage.SOFT,
                    reasons=reasons,
                    features=asdict(features),
                )

            return False

        return True

    def hard_check_short(self, features, indicators):
        hard = BREAKOUT_SHORT_HARD
        reasons = []

        if features.close_above_level:
            reasons.append("no_close_below_low")

        if features.breakout_strength_pct < hard["min_strength"]:
            reasons.append(
                f"weak_strength {features.breakout_strength_pct:.4f}"
            )

        if hard["require_ema_alignment"] and not features.htf_confirmed:
            reasons.append("ema_alignment")

        adx15 = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0
        adx1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0

        if adx15 < hard["min_adx"] or adx1h < hard["min_adx_1h"]:
            reasons.append(
                f"weak_adx {adx15:.1f}/{adx1h:.1f}"
            )

        if reasons:
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT_HARD)

            if self.breakout_rejection:
                self.breakout_rejection.add(
                    timestamp=self._current_ts,
                    symbol=self._current_symbol,
                    side="SHORT",
                    stage=RejectionStage.HARD,
                    reasons=reasons,
                    features=asdict(features),
                )

            return False

        return True

    def soft_check_short(self, features, indicators):
        soft = BREAKOUT_SHORT_SOFT
        reasons = []

        if indicators.volume_ratio < soft["min_volume_ratio"]:
            reasons.append(
                f"low_volume {indicators.volume_ratio:.2f}"
            )

        if indicators.ema_slope > soft["max_ema_slope"]:
            reasons.append(
                f"weak_ema_slope {indicators.ema_slope:.5f}"
            )

        if indicators.rsi > soft["max_rsi"]:
            reasons.append(
                f"weak_rsi {indicators.rsi:.1f}"
            )

        if features.candle_body_ratio < soft["min_body_ratio"]:
            reasons.append(
                f"small_body {features.candle_body_ratio:.2f}"
            )

        if features.distance_from_level_pct > soft["max_close_to_low_pct"]:
            reasons.append(
                f"poor_close_location {features.distance_from_level_pct:.3f}"
            )

        passed_soft = 5 - len(reasons)

        if passed_soft < 3:
            if self.reject_stats:
                self.reject_stats.reject(
                    RejectReason.BREAKOUT_SHORT
                )

            if self.breakout_rejection:
                self.breakout_rejection.add(
                    timestamp=self._current_ts,
                    symbol=self._current_symbol,
                    side="SHORT",
                    stage=RejectionStage.SOFT,
                    reasons=reasons,
                    features=asdict(features),
                )

            return False

        return True
