from __future__ import annotations

from dataclasses import asdict

from app.core.constants import BREAKOUT
from core.enums import RejectReason
from core.logger import log, LogType
from core.types import MarketStructure
from strategy.models import SetupCandidate
from strategy.trend_following.breakout.config import (
    BREAKOUT_LONG_HARD,
    BREAKOUT_LONG_SOFT,
    BREAKOUT_SHORT_HARD,
    BREAKOUT_SHORT_SOFT,
)
from strategy.trend_following.breakout.feature_builder import FeatureBuilder


class BreakoutDetector:

    def __init__(self):
        self.reject_stats = None

    def detect(self, market_state):
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
        close_above = features.close_above_level == hard["close_above_recent_high"]
        strength_ok = features.breakout_strength_pct >= hard["min_strength"]
        ema_ok = features.htf_confirmed == hard["require_ema_alignment"]
        adx_val_15m = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0.0
        adx_val_1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0.0
        adx_ok = adx_val_15m >= hard["min_adx"] and adx_val_1h >= hard["min_adx_1h"]

        if not (close_above and strength_ok and ema_ok and adx_ok):
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT)
            return False

        return True

    def soft_check_long(self, features, indicators):
        soft = BREAKOUT_LONG_SOFT
        vol_ok = indicators.volume_ratio >= soft["min_volume_ratio"]
        ema_slope_ok = indicators.ema_slope >= soft["min_ema_slope"]
        rsi_ok = indicators.rsi >= soft["min_rsi"]
        body_ok = features.candle_body_ratio >= soft["min_body_ratio"]
        close_loc_ok = features.distance_from_level_pct <= soft["max_close_to_high_pct"]
        passed_soft = sum((vol_ok, ema_slope_ok, rsi_ok, body_ok, close_loc_ok))

        if passed_soft < 3:
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT)
            return False

        return True

    def hard_check_short(self, features, indicators):
        hard = BREAKOUT_SHORT_HARD
        close_below = not features.close_above_level == hard["close_below_recent_low"]
        strength_ok = features.breakout_strength_pct >= hard["min_strength"]
        ema_ok = features.htf_confirmed == hard["require_ema_alignment"]
        adx_val_15m = float(indicators.adx_15m.iloc[-1]) if indicators.adx_15m is not None else 0.0
        adx_val_1h = float(indicators.adx_1h.iloc[-1]) if indicators.adx_1h is not None else 0.0
        adx_ok = adx_val_15m >= hard["min_adx"] and adx_val_1h >= hard["min_adx_1h"]

        if not (close_below and strength_ok and ema_ok and adx_ok):
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT)
            return False

        return True

    def soft_check_short(self, features, indicators):
        soft = BREAKOUT_SHORT_SOFT
        vol_ok = indicators.volume_ratio >= soft["min_volume_ratio"]
        ema_slope_ok = indicators.ema_slope <= soft["max_ema_slope"]
        rsi_ok = indicators.rsi <= soft["max_rsi"]
        body_ok = features.candle_body_ratio >= soft["min_body_ratio"]
        close_loc_ok = features.distance_from_level_pct <= soft["max_close_to_low_pct"]
        passed_soft = sum((vol_ok, ema_slope_ok, rsi_ok, body_ok, close_loc_ok))

        if passed_soft < 3:
            if self.reject_stats:
                self.reject_stats.reject(RejectReason.BREAKOUT)
            return False

        return True
