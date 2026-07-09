from __future__ import annotations

import pandas as pd

from market_analyzer.feature import (
    BreakoutFeatures,
    PullbackFeatures,
    RetestFeatures,
    SetupFeatures,
    SweepFeatures,
)
from market_analyzer.market_trend import calculate_ema


def _safe_float(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError, IndexError):
        return default


def _safe_bool(v, default: bool = False) -> bool:
    try:
        return bool(v)
    except Exception:
        return default


def compute_breakout_features(data_15m: pd.DataFrame | None, indicators: dict | None = None) -> BreakoutFeatures:
    if data_15m is None or len(data_15m) < 20:
        return BreakoutFeatures()

    try:
        close = data_15m["close"].astype(float)
        open_ = data_15m["open"].astype(float)
        high = data_15m["high"].astype(float)
        low = data_15m["low"].astype(float)
        vol = data_15m["volume"].astype(float)

        price = float(close.iloc[-1])
        recent_high_7 = float(high.iloc[-7:-1].max())
        recent_low_7 = float(low.iloc[-7:-1].min())
        recent_high_20 = float(high.iloc[-20:].max())
        recent_low_20 = float(low.iloc[-20:].min())

        breakout_up = price > recent_high_7
        breakout_down = price < recent_low_7

        volume_ratio = float(vol.iloc[-1]) / max(float(vol.iloc[-20:].mean()), 1e-12)

        strength_up = (price - recent_high_7) / max(price, 1e-12) if breakout_up else 0.0
        strength_down = (recent_low_7 - price) / max(price, 1e-12) if breakout_down else 0.0

        candle_rng = max(float(high.iloc[-1]) - float(low.iloc[-1]), 1e-12)
        body_ratio = abs(price - float(open_.iloc[-1])) / candle_rng
        close_to_high_pct = (float(high.iloc[-1]) - price) / candle_rng
        close_to_low_pct = (price - float(low.iloc[-1])) / candle_rng

        ind = indicators or {}
        ema_slope = float(ind.get("ema20_slope_15m", 0.0))
        rsi = float(ind.get("rsi_15m", 50.0))
        atr_percent = float(ind.get("atr_percent", 0.0))

        ema20 = calculate_ema(data_15m, 20)
        ema_val = float(ema20.iloc[-1])
        ema_bullish_alignment = price > ema_val
        ema_bearish_alignment = price < ema_val

        return BreakoutFeatures(
            recent_high_7=recent_high_7,
            recent_low_7=recent_low_7,
            recent_high_20=recent_high_20,
            recent_low_20=recent_low_20,
            breakout_up=breakout_up,
            breakout_down=breakout_down,
            close_above_recent_high=price > recent_high_7,
            close_below_recent_low=price < recent_low_7,
            breakout_strength=max(strength_up, strength_down),
            breakout_distance_pct=abs(price - recent_high_7) / max(recent_high_7, 1e-12) if breakout_up else abs(price - recent_low_7) / max(recent_low_7, 1e-12) if breakout_down else 0.0,
            momentum_up=breakout_up and strength_up > 0.0,
            momentum_down=breakout_down and strength_down > 0.0,
            volume_ratio=volume_ratio,
            body_ratio=body_ratio,
            close_to_high_pct=close_to_high_pct,
            close_to_low_pct=close_to_low_pct,
            ema_slope=ema_slope,
            ema_bullish_alignment=ema_bullish_alignment,
            ema_bearish_alignment=ema_bearish_alignment,
            rsi=rsi,
            atr_percent=atr_percent,
        )
    except Exception:
        return BreakoutFeatures()


def compute_pullback_features(data_15m: pd.DataFrame | None) -> PullbackFeatures:
    if data_15m is None or len(data_15m) < 20:
        return PullbackFeatures()

    try:
        close = data_15m["close"].astype(float)
        open_ = data_15m["open"].astype(float)
        high = data_15m["high"].astype(float)
        low = data_15m["low"].astype(float)
        vol = data_15m["volume"].astype(float)

        price = float(close.iloc[-1])
        ema20 = calculate_ema(data_15m, 20)
        ema_val = float(ema20.iloc[-1])

        if ema_val <= 0:
            return PullbackFeatures()

        ema_dev = abs(price - ema_val) / max(ema_val, 1e-12)

        bullish = price > float(open_.iloc[-1])
        bearish = price < float(open_.iloc[-1])
        body_size = abs(price - float(open_.iloc[-1]))
        rng = max(float(high.iloc[-1]) - float(low.iloc[-1]), 1e-12)
        body_r = body_size / rng

        prior_high = float(high.iloc[-2])
        prior_low = float(low.iloc[-2])
        prior_mid = (prior_high + prior_low) / 2.0

        momentum_up = price > float(close.iloc[-2]) and float(high.iloc[-1]) >= prior_high
        momentum_down = price < float(close.iloc[-2]) and float(low.iloc[-1]) <= prior_low

        impulse_pct = (float(close.iloc[-4]) - float(close.iloc[-12])) / max(abs(float(close.iloc[-12])), 1e-12)

        volume_ratio = float(vol.iloc[-1]) / max(float(vol.iloc[-20:].mean()), 1e-12)

        close_above_prior_mid = price > prior_mid
        close_below_prior_mid = price < prior_mid

        reclaim_long = (
            bullish
            and body_r >= 0.50
            and close_above_prior_mid
            and price > prior_high
            and momentum_up
        )
        reclaim_short = (
            bearish
            and body_r >= 0.50
            and close_below_prior_mid
            and price < prior_low
            and momentum_down
        )

        return PullbackFeatures(
            price=price,
            ema_val=ema_val,
            ema_deviation_pct=ema_dev,
            in_pullback_zone_long=price >= ema_val * 0.99 and price <= ema_val * 1.003,
            in_pullback_zone_short=price <= ema_val * 1.01 and price >= ema_val * 0.997,
            bullish_body=bullish,
            bearish_body=bearish,
            body_size=body_size,
            range_size=rng,
            body_ratio=body_r,
            prior_high=prior_high,
            prior_low=prior_low,
            prior_mid=prior_mid,
            close_above_prior_high=price > prior_high,
            close_below_prior_low=price < prior_low,
            close_above_prior_mid=close_above_prior_mid,
            close_below_prior_mid=close_below_prior_mid,
            momentum_up=momentum_up,
            momentum_down=momentum_down,
            impulse_pct=impulse_pct,
            volume_ratio=volume_ratio,
            reclaim_long=reclaim_long,
            reclaim_short=reclaim_short,
        )
    except Exception:
        return PullbackFeatures()


def compute_retest_features(data_15m: pd.DataFrame | None) -> RetestFeatures:
    if data_15m is None or len(data_15m) < 20:
        return RetestFeatures()

    try:
        close = data_15m["close"].astype(float)
        open_ = data_15m["open"].astype(float)
        high = data_15m["high"].astype(float)
        low = data_15m["low"].astype(float)

        price = float(close.iloc[-1])
        level_up = float(high.iloc[-12:-3].max())
        level_dn = float(low.iloc[-12:-3].min())

        max_dev = 0.003
        min_reclaim = 0.001

        breakout_seen_up = float(close.iloc[-3:-1].max()) > level_up * 1.001
        touched_level_up = float(low.iloc[-1]) <= level_up * (1.0 + max_dev)
        reclaimed_up = price > level_up * (1.0 + min_reclaim) and price > float(open_.iloc[-1])

        breakout_seen_dn = float(close.iloc[-3:-1].min()) < level_dn * 0.999
        touched_level_dn = float(high.iloc[-1]) >= level_dn * (1.0 - max_dev)
        reclaimed_dn = price < level_dn * (1.0 - min_reclaim) and price < float(open_.iloc[-1])

        range_size = max(float(high.iloc[-1]) - float(low.iloc[-1]), 1e-12)
        body_r = abs(price - float(open_.iloc[-1])) / range_size

        close_strength_up = (price - float(low.iloc[-1])) / range_size
        close_strength_dn = (float(high.iloc[-1]) - price) / range_size

        vol = data_15m["volume"].astype(float) if "volume" in data_15m.columns else None
        vol_r = float(vol.iloc[-1]) / max(float(vol.iloc[-20:].mean()), 1e-12) if vol is not None else 0.0

        nearest_level = level_up if abs(price - level_up) < abs(price - level_dn) else level_dn
        distance = abs(price - nearest_level) / max(nearest_level, 1e-12)

        return RetestFeatures(
            breakout_level=nearest_level,
            distance_from_breakout_level_pct=distance,
            touched_breakout_level=touched_level_up or touched_level_dn,
            retest_rejection_long=reclaimed_up,
            retest_rejection_short=reclaimed_dn,
            body_ratio=body_r,
            close_strength=max(close_strength_up, close_strength_dn),
            vol_ratio=vol_r,
            bullish_retest_confirm=breakout_seen_up and touched_level_up and reclaimed_up,
            bearish_retest_confirm=breakout_seen_dn and touched_level_dn and reclaimed_dn,
        )
    except Exception:
        return RetestFeatures()


def compute_sweep_features(data_15m: pd.DataFrame | None) -> SweepFeatures:
    if data_15m is None or len(data_15m) < 30:
        return SweepFeatures()

    try:
        close = data_15m["close"].astype(float)
        open_ = data_15m["open"].astype(float)
        high = data_15m["high"].astype(float)
        low = data_15m["low"].astype(float)
        vol = data_15m["volume"].astype(float)

        price = float(close.iloc[-1])
        swing_high = float(high.iloc[-15:-1].max())
        swing_low = float(low.iloc[-15:-1].min())

        swept_high = float(high.iloc[-1]) > swing_high
        swept_low = float(low.iloc[-1]) < swing_low

        upper_wick = float(high.iloc[-1]) - max(price, float(open_.iloc[-1]))
        lower_wick = min(price, float(open_.iloc[-1])) - float(low.iloc[-1])
        rng = max(float(high.iloc[-1]) - float(low.iloc[-1]), 1e-12)
        upper_wick_ratio = upper_wick / rng
        lower_wick_ratio = lower_wick / rng
        body_ratio = abs(price - float(open_.iloc[-1])) / rng

        volume_ratio = float(vol.iloc[-1]) / max(float(vol.iloc[-20:].mean()), 1e-12)

        reclaimed_high = swept_high and price < swing_high and price < float(open_.iloc[-1])
        reclaimed_low = swept_low and price > swing_low and price > float(open_.iloc[-1])

        return SweepFeatures(
            swing_high=swing_high,
            swing_low=swing_low,
            swept_high=swept_high,
            swept_low=swept_low,
            reclaimed_after_high_sweep=reclaimed_high,
            reclaimed_after_low_sweep=reclaimed_low,
            upper_wick=upper_wick,
            lower_wick=lower_wick,
            upper_wick_ratio=upper_wick_ratio,
            lower_wick_ratio=lower_wick_ratio,
            body_ratio=body_ratio,
            distance_from_swing_high_pct=abs(price - swing_high) / max(swing_high, 1e-12) if swing_high > 0 else 0.0,
            distance_from_swing_low_pct=abs(price - swing_low) / max(swing_low, 1e-12) if swing_low > 0 else 0.0,
            volume_ratio=volume_ratio,
            rejection_long=reclaimed_low and lower_wick_ratio >= 0.45,
            rejection_short=reclaimed_high and upper_wick_ratio >= 0.45,
        )
    except Exception:
        return SweepFeatures()


def build_features(
    data_5m: pd.DataFrame | None = None,
    data_15m: pd.DataFrame | None = None,
    data_1h: pd.DataFrame | None = None,
    indicators: dict | None = None,
) -> SetupFeatures:
    return SetupFeatures(
        breakout=compute_breakout_features(data_15m, indicators),
        pullback=compute_pullback_features(data_15m),
        retest=compute_retest_features(data_15m),
        sweep=compute_sweep_features(data_15m),
    )
