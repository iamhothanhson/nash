from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.coins.loader import get_coin_config, scale_atr_stop_mult
from strategy.trend_following.base_trend_following import TrendFollowingStrategyBase
from strategy.trend_following.trend_following_config import (
    TREND_BREAKOUT_STOP_ATR_MULT,
    TREND_STOP_ATR_MULT,
)


def _flat_15m(price: float, n: int = 30) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "high": [price * 1.01] * n,
            "low": [price * 0.99] * n,
            "close": [price] * n,
            "open": [price] * n,
        }
    )


def test_fet_atr_multiplier_default_is_unity() -> None:
    cfg = get_coin_config("FETUSDT")
    scaled = scale_atr_stop_mult(float(TREND_STOP_ATR_MULT), cfg)
    assert scaled == pytest.approx(float(TREND_STOP_ATR_MULT))


def test_scale_atr_stop_mult_halves_when_coin_override() -> None:
    cfg = {"atr_multiplier": 0.5}
    scaled = scale_atr_stop_mult(float(TREND_STOP_ATR_MULT), cfg)
    assert scaled == pytest.approx(float(TREND_STOP_ATR_MULT) * 0.5)


def test_trend_pullback_stop_tightens_with_lower_coin_mult() -> None:
    strat = TrendFollowingStrategyBase()
    df = _flat_15m(0.27, 30)
    entry = 0.2727
    anchor = 0.275
    cfg = {"atr_multiplier": 0.5}
    default_sl = strat.get_stop_loss(entry, "SHORT", df, anchor)
    tight_sl = strat.get_stop_loss(entry, "SHORT", df, anchor, cfg=cfg)
    assert default_sl is not None
    assert tight_sl is not None
    assert tight_sl[1] < default_sl[1]
