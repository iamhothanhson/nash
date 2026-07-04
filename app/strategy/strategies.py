from __future__ import annotations

from setup_builder.builder import Setup, SetupType
from strategy.trend_following.config import (
    TREND_BREAKOUT_NEAR_MISS_MIN_CONFIDENCE,
    TREND_BREAKOUT_NEAR_MISS_MIN_SCORE,
    TREND_REGIME_ADX_CATASTROPHIC,
)
from strategy.liquidity_sweep_reversal.sweep_revesal_config import VOLATILITY_THRESHOLD
from coins.loader import get_coin_config
from config import settings


def _trend_score_thresholds(cfg: dict, setup_type: str) -> tuple[int, int]:
    min_ap = int(
        cfg.get(
            "trend_min_setup_score_a_plus",
            cfg["min_setup_score_a_plus"],
        )
    )
    min_a = int(cfg.get("trend_min_setup_score", cfg["min_setup_score"]))
    stype = str(setup_type).strip().lower()
    if stype:
        key = stype.replace("-", "_")
        min_ap = int(
            cfg.get(
                f"trend_{key}_min_setup_score_a_plus",
                cfg.get(f"{key}_min_setup_score_a_plus", min_ap),
            )
        )
        min_a = int(
            cfg.get(
                f"trend_{key}_min_setup_score",
                cfg.get(f"{key}_min_setup_score", min_a),
            )
        )
    return min_ap, min_a


def _trend_score_bonus(cfg: dict, setup_type: str) -> int:
    bonus = int(cfg.get("trend_score_bonus", 0) or 0)
    stype = str(setup_type).strip().lower()
    if stype:
        key = stype.replace("-", "_")
        bonus += int(cfg.get(f"trend_{key}_score_bonus", 0) or 0)
    return bonus


class BreakoutStrategy:
    """Trend-following strategy adapter — builds breakout/retest/pullback signals."""

    def supports_setup(self, setup: Setup) -> bool:
        return setup.side is not None

    def generate_signal(self, setup: Setup) -> object | None:
        if setup.side is None or setup.grade == "Skip":
            return None

        ms = setup.market_state
        d15 = getattr(ms, "data_15m", None)
        d5 = getattr(ms, "data_5m", None)
        if d15 is None or d5 is None:
            return None

        cfg = get_coin_config(setup.symbol)
        entry = float(d5["close"].iloc[-1])
        ind = ms.indicators or {}

        volatility = float(ind.get("atr_15m", 0)) / entry if entry > 0 else 0
        if volatility < VOLATILITY_THRESHOLD:
            return None

        adx_v = float(ind.get("adx_15m", 0.0))
        catastrophic = float(TREND_REGIME_ADX_CATASTROPHIC)
        if adx_v < catastrophic:
            return None

        score = int(round(setup.score)) + _trend_score_bonus(cfg, setup.setup_type.value)

        if volatility > float(cfg.get("volatility_threshold", 0.004)):
            score += 1

        min_ap, min_a = _trend_score_thresholds(cfg, setup.setup_type.value)
        near_miss = (
            setup.setup_type == SetupType.BREAKOUT
            and score >= int(TREND_BREAKOUT_NEAR_MISS_MIN_SCORE)
            and float(setup.confidence) >= float(TREND_BREAKOUT_NEAR_MISS_MIN_CONFIDENCE)
        )
        if score < min_a and not near_miss:
            return None

        from signal.builder import build_signal

        return build_signal(setup, entry)


class LiquiditySweepStrategy:
    """Liquidity-sweep-reversal strategy adapter."""

    def __init__(self):
        from strategy.liquidity_sweep_reversal.base_sweep_revesal import LiquiditySweepReversalBase
        self._strategy = LiquiditySweepReversalBase()

    def supports_setup(self, setup: Setup) -> bool:
        return True

    def generate_signal(self, setup: Setup) -> object | None:
        ms = setup.market_state
        d15 = getattr(ms, "data_15m", None)
        d5 = getattr(ms, "data_5m", None)
        d1h = getattr(ms, "data_1h", None)
        if d15 is None or d5 is None or d1h is None:
            return None
        return self._strategy.build_signal(d1h, d15, d5, symbol=setup.symbol, market_state=ms)
