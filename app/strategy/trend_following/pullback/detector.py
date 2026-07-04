from __future__ import annotations

from strategy.trend_following.config import (
    PULLBACK_EMA_SLOPE_MIN,
    PULLBACK_LONG_RSI_MIN,
    PULLBACK_SHORT_RSI_MAX,
    TREND_PULLBACK_MAX_EMA_DEV,
    TREND_PULLBACK_RECLAIM_BODY_RATIO,
    TREND_PULLBACK_IMPULSE_PCT_MIN,
)
from config.constants import PULLBACK
from strategy.trend_following.types import SetupCandidate


def _cfg_float(cfg: dict | None, key: str, default: float) -> float:
    if not isinstance(cfg, dict):
        return float(default)
    try:
        return float(cfg.get(key, default))
    except (TypeError, ValueError):
        return float(default)


class PullbackDetector:
    pullback_long = staticmethod(lambda market_state: PullbackDetector.detect_long(market_state))
    pullback_short = staticmethod(lambda market_state: PullbackDetector.detect_short(market_state))

    @staticmethod
    def detect_long(market_state, *, cfg: dict | None = None) -> SetupCandidate | None:
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        pf = features.pullback
        ind = market_state.indicators or {}

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi_raw = ind.get("rsi_15m", 0.0)
        rsi = float(rsi_raw.iloc[-1]) if hasattr(rsi_raw, "iloc") else float(rsi_raw)

        price = pf.price
        ema_val = pf.ema_val
        if ema_val <= 0:
            return None

        ema_slope_min = _cfg_float(cfg, "trend_pullback_ema_slope_min", PULLBACK_EMA_SLOPE_MIN)
        max_dev = _cfg_float(cfg, "trend_pullback_max_ema_dev", TREND_PULLBACK_MAX_EMA_DEV)
        slope_boost = 1.6 if ema_slope > (ema_slope_min * 1.3) else 1.25
        dynamic_max_dev = max_dev * slope_boost
        upper_zone_mult = _cfg_float(cfg, "trend_pullback_upper_zone_mult", 0.6)

        in_pullback_zone = (
            price >= ema_val * (1.0 - dynamic_max_dev)
            and price <= ema_val * (1.0 + dynamic_max_dev * upper_zone_mult)
        )

        ema_dev = pf.ema_deviation_pct
        reclaim = pf.reclaim_long
        body_ratio = pf.body_ratio
        min_body_ratio = _cfg_float(cfg, "trend_pullback_reclaim_body_ratio", TREND_PULLBACK_RECLAIM_BODY_RATIO)
        impulse_pct = pf.impulse_pct
        impulse_pct_min = _cfg_float(cfg, "trend_pullback_impulse_pct_min", TREND_PULLBACK_IMPULSE_PCT_MIN)
        has_impulse = impulse_pct > impulse_pct_min
        vol_confirm = pf.volume_ratio >= _cfg_float(cfg, "trend_pullback_vol_confirm_ratio", 0.9)

        if (
            ema_slope > ema_slope_min
            and in_pullback_zone
            and rsi > _cfg_float(cfg, "trend_pullback_long_rsi_min", PULLBACK_LONG_RSI_MIN)
            and reclaim
            and ema_dev <= dynamic_max_dev
            and has_impulse
        ):
            return SetupCandidate(
                setup_type=PULLBACK,
                direction="LONG",
                anchor=float(ema_val),
                setup_points=0,
                key_level_points=0,
                confirmation_points=0,
                raw_score=0.0,
                trigger_type="pullback_long",
                confidence=0.0,
                debug_reason=(
                    f"ema_dev={ema_dev:.6f},dynamic_max_dev={dynamic_max_dev:.6f},"
                    f"body_ratio={body_ratio:.3f},vol_confirm={vol_confirm},"
                    f"impulse_pct={impulse_pct:.4f},"
                ),
            )
        return None

    @staticmethod
    def detect_short(market_state, *, cfg: dict | None = None) -> SetupCandidate | None:
        features = getattr(market_state, "features", None)
        if features is None:
            return None
        pf = features.pullback
        ind = market_state.indicators or {}

        ema_slope = float(ind.get("ema_slope_15m", 0.0))
        rsi_raw = ind.get("rsi_15m", 0.0)
        rsi = float(rsi_raw.iloc[-1]) if hasattr(rsi_raw, "iloc") else float(rsi_raw)

        price = pf.price
        ema_val = pf.ema_val
        if ema_val <= 0:
            return None

        ema_slope_min = _cfg_float(cfg, "trend_pullback_ema_slope_min", PULLBACK_EMA_SLOPE_MIN)
        max_dev = _cfg_float(cfg, "trend_pullback_max_ema_dev", TREND_PULLBACK_MAX_EMA_DEV)
        slope_boost = 1.6 if ema_slope < -(ema_slope_min * 1.3) else 1.25
        dynamic_max_dev = max_dev * slope_boost
        upper_zone_mult = _cfg_float(cfg, "trend_pullback_upper_zone_mult", 0.6)

        in_pullback_zone = (
            price <= ema_val * (1.0 + dynamic_max_dev)
            and price >= ema_val * (1.0 - dynamic_max_dev * upper_zone_mult)
        )

        ema_dev = pf.ema_deviation_pct
        reclaim = pf.reclaim_short
        body_ratio = pf.body_ratio
        min_body_ratio = _cfg_float(cfg, "trend_pullback_reclaim_body_ratio", TREND_PULLBACK_RECLAIM_BODY_RATIO)
        impulse_pct = pf.impulse_pct
        impulse_pct_min = _cfg_float(cfg, "trend_pullback_impulse_pct_min", TREND_PULLBACK_IMPULSE_PCT_MIN)
        has_impulse = impulse_pct < -impulse_pct_min
        vol_confirm = pf.volume_ratio >= _cfg_float(cfg, "trend_pullback_vol_confirm_ratio", 0.9)

        if (
            ema_slope < -ema_slope_min
            and in_pullback_zone
            and rsi < _cfg_float(cfg, "trend_pullback_short_rsi_max", PULLBACK_SHORT_RSI_MAX)
            and reclaim
            and ema_dev <= dynamic_max_dev
            and has_impulse
        ):
            return SetupCandidate(
                setup_type=PULLBACK,
                direction="SHORT",
                anchor=float(ema_val),
                setup_points=0,
                key_level_points=0,
                confirmation_points=0,
                raw_score=0.0,
                trigger_type="pullback_short",
                confidence=0.0,
                debug_reason=(
                    f"ema_dev={ema_dev:.6f},dynamic_max_dev={dynamic_max_dev:.6f},"
                    f"body_ratio={body_ratio:.3f},vol_confirm={vol_confirm},"
                    f"impulse_pct={impulse_pct:.4f},"
                ),
            )
        return None
