from __future__ import annotations

from config.constants import BREAKOUT
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT
from strategy.trend_following.breakout.feature_builder import FeatureBuilder


class BreakoutDetector:

    def is_breakout_long(features, indicators):
        values = {
            # Breakout features
            "close_above_recent_high": features.close_above_recent_high,
            "strength": features.strength,
            "strength_atr_factor": features.strength_atr_factor,
            "body_ratio": features.body_ratio,
            "close_to_high_pct": features.close_to_high_pct,
            "ema_alignment": features.ema_alignment,
            "sl_distance": features.sl_distance,

            # Indicators
            "volume_ratio": indicators.volume_ratio,
            "ema_slope": indicators.ema_slope,
            "rsi": indicators.rsi,
        }
        return (
            values["close_above_recent_high"] == BREAKOUT_LONG["close_above_recent_high"]
            and values["strength"] >= BREAKOUT_LONG["min_strength"]
            and values["strength_atr_factor"] >= BREAKOUT_LONG["min_strength_atr_factor"]
            and values["volume_ratio"] >= BREAKOUT_LONG["min_volume_ratio"]
            and values["ema_slope"] >= BREAKOUT_LONG["min_ema_slope"]
            and values["rsi"] >= BREAKOUT_LONG["min_rsi"]
            and values["body_ratio"] >= BREAKOUT_LONG["min_body_ratio"]
            and values["close_to_high_pct"] <= BREAKOUT_LONG["max_close_to_high_pct"]
            and values["ema_alignment"] == BREAKOUT_LONG["require_ema_alignment"]
            and values["sl_distance"] >= BREAKOUT_LONG["min_sl_distance"]
        )

    def breakout_long_candidate(self, market_state):
        breakout_feature = FeatureBuilder.compute_breakout_features(market_state.data_15m, market_state.indicators)

        if not self.is_breakout_long(breakout_feature, market_state.indicators):
            return None
        return SetupCandidate(
            setup_type=BREAKOUT,
            direction="LONG",
            trigger_type="breakout",
            anchor=breakout_feature.breakout_level,
            detected_at=market_state.timestamp,
            timeframe=market_state.timeframe,
        )

    def breakout_short_candidate(self, market_state):
        breakout_feature = FeatureBuilder.compute_breakout_features(market_state.data_15m, market_state.indicators)
        if breakout_feature.breakout_level <= 0 or breakout_feature.direction != "SHORT":
            return None
        if not self._validate_short(breakout_feature, market_state.indicators):
            return None
        return SetupCandidate(
            setup_type=BREAKOUT,
            direction="SHORT",
            trigger_type="breakout",
            anchor=breakout_feature.breakout_level,
            detected_at=market_state.timestamp,
            timeframe=market_state.timeframe,
        )