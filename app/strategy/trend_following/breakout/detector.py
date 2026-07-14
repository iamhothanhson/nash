from __future__ import annotations

from dataclasses import asdict

from config.constants import BREAKOUT
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

    def detect(self, market_state):
        sym = market_state.symbol
        structure = market_state.structure
        breakout_feature = FeatureBuilder.compute_breakout_features(
            market_state.data_15m, market_state.indicators
        )

        if structure == MarketStructure.HHHL:
            result = self._check_long(breakout_feature, market_state.indicators)
            if result is None:
                return None
            passed_soft, details = result
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
                log(LogType.PLAN_REJECT, sym,
                    f"Breakout Short Rejected: level={breakout_feature.breakout_level}"
                    f" direction={breakout_feature.direction}")
                return None
            result = self._check_short(breakout_feature, market_state.indicators)
            if result is None:
                return None
            passed_soft, details = result
            return SetupCandidate(
                setup_type=BREAKOUT,
                direction="SHORT",
                trigger_type="breakout",
                anchor=breakout_feature.breakout_level,
                features=asdict(breakout_feature),
                detected_at=market_state.timestamp,
                timeframe=market_state.timeframe,
            )

        log(LogType.PLAN_REJECT, sym, f"structure={structure.value} Skipped Breakout")
        return None

    def _check_long(self, features, indicators):
        hard = BREAKOUT_LONG_HARD
        close_above = features.close_above_level == hard["close_above_recent_high"]
        strength_ok = features.breakout_strength_pct >= hard["min_strength"]
        ema_ok = features.htf_confirmed == hard["require_ema_alignment"]

        if not (close_above and strength_ok and ema_ok):
            log(LogType.PLAN_REJECT, indicators.symbol,
                f"long hard: close_above={close_above} "
                f"strength={features.breakout_strength_pct:.4f}/{hard['min_strength']} "
                f"ema_aligned={ema_ok}")
            return None

        soft = BREAKOUT_LONG_SOFT
        vol_ok = indicators.volume_ratio >= soft["min_volume_ratio"]
        ema_slope_ok = indicators.ema_slope >= soft["min_ema_slope"]
        rsi_ok = indicators.rsi >= soft["min_rsi"]
        body_ok = features.candle_body_ratio >= soft["min_body_ratio"]
        close_loc_ok = features.distance_from_level_pct <= soft["max_close_to_high_pct"]
        soft_checks = (vol_ok, ema_slope_ok, rsi_ok, body_ok, close_loc_ok)
        passed_soft = sum(soft_checks)

        if passed_soft < 3:
            log(LogType.PLAN_REJECT, indicators.symbol,
                f"long soft: vol={vol_ok}({indicators.volume_ratio:.2f}) "
                f"slope={ema_slope_ok}({indicators.ema_slope:.4f}) "
                f"rsi={rsi_ok}({indicators.rsi:.1f}) "
                f"body={body_ok}({features.candle_body_ratio:.2f}) "
                f"loc={close_loc_ok}({features.distance_from_level_pct:.3f}) "
                f"passed={passed_soft}")
            return None

        return passed_soft, soft_checks

    def _check_short(self, features, indicators):
        hard = BREAKOUT_SHORT_HARD
        close_below = not features.close_above_level == hard["close_below_recent_low"]
        strength_ok = features.breakout_strength_pct >= hard["min_strength"]
        ema_ok = features.htf_confirmed == hard["require_ema_alignment"]

        if not (close_below and strength_ok and ema_ok):
            log(LogType.PLAN_REJECT, indicators.symbol,
                f"short hard: close_below={close_below} "
                f"strength={features.breakout_strength_pct:.4f}/{hard['min_strength']} "
                f"ema_aligned={ema_ok}")
            return None

        soft = BREAKOUT_SHORT_SOFT
        vol_ok = indicators.volume_ratio >= soft["min_volume_ratio"]
        ema_slope_ok = indicators.ema_slope <= soft["max_ema_slope"]
        rsi_ok = indicators.rsi <= soft["max_rsi"]
        body_ok = features.candle_body_ratio >= soft["min_body_ratio"]
        close_loc_ok = features.distance_from_level_pct <= soft["max_close_to_low_pct"]
        soft_checks = (vol_ok, ema_slope_ok, rsi_ok, body_ok, close_loc_ok)
        passed_soft = sum(soft_checks)

        if passed_soft < 3:
            log(LogType.PLAN_REJECT, indicators.symbol,
                f"short soft: vol={vol_ok}({indicators.volume_ratio:.2f}) "
                f"slope={ema_slope_ok}({indicators.ema_slope:.4f}) "
                f"rsi={rsi_ok}({indicators.rsi:.1f}) "
                f"body={body_ok}({features.candle_body_ratio:.2f}) "
                f"loc={close_loc_ok}({features.distance_from_level_pct:.3f}) "
                f"passed={passed_soft}")
            return None

        return passed_soft, soft_checks
