from __future__ import annotations

from dataclasses import asdict

from config.constants import BREAKOUT
from core.types import MarketStructure
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT
from strategy.trend_following.breakout.feature_builder import FeatureBuilder


class BreakoutDetector:

    def detect(self, market_state):
        structure = market_state.structure
        breakout_feature = FeatureBuilder.compute_breakout_features(market_state.data_15m, market_state.indicators)

        if structure == MarketStructure.HHHL:
            if not self.is_breakout_long(breakout_feature, market_state.indicators):
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

        if structure == MarketStructure.LHLL:
            if breakout_feature.breakout_level <= 0 or breakout_feature.direction != "SHORT":
                return None
            if not self.is_breakout_short(breakout_feature, market_state.indicators):
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

    def is_breakout_long(self, features, indicators):
        return (
            features.close_above_level == BREAKOUT_LONG["close_above_recent_high"]
            and features.breakout_strength_pct >= BREAKOUT_LONG["min_strength"]
            and indicators.volume_ratio >= BREAKOUT_LONG["min_volume_ratio"]
            and indicators.ema_slope >= BREAKOUT_LONG["min_ema_slope"]
            and indicators.rsi >= BREAKOUT_LONG["min_rsi"]
            and features.candle_body_ratio >= BREAKOUT_LONG["min_body_ratio"]
            and features.distance_from_level_pct <= BREAKOUT_LONG["max_close_to_high_pct"]
            and features.htf_confirmed == BREAKOUT_LONG["require_ema_alignment"]
        )

    def is_breakout_short(self, features, indicators):
        return (
            not features.close_above_level == BREAKOUT_SHORT["close_below_recent_low"]
            and features.breakout_strength_pct >= BREAKOUT_SHORT["min_strength"]
            and indicators.volume_ratio >= BREAKOUT_SHORT["min_volume_ratio"]
            and indicators.ema_slope <= BREAKOUT_SHORT["max_ema_slope"]
            and indicators.rsi <= BREAKOUT_SHORT["max_rsi"]
            and features.candle_body_ratio >= BREAKOUT_SHORT["min_body_ratio"]
            and features.distance_from_level_pct <= BREAKOUT_SHORT["max_close_to_low_pct"]
            and features.htf_confirmed == BREAKOUT_SHORT["require_ema_alignment"]
        )