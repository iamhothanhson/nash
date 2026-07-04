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

from app.coins.loader import get_coin_config
from strategy.liquidity_sweep_reversal.base_sweep_revesal import LiquiditySweepReversalBase


def _flat_15m(price: float, n: int = 30, *, range_pct: float = 0.001) -> pd.DataFrame:
    """Low-volatility bars so ATR-based stop distance stays under MAX_SL_DISTANCE (2%)."""
    return pd.DataFrame(
        {
            "high": [price * (1.0 + range_pct)] * n,
            "low": [price * (1.0 - range_pct)] * n,
            "close": [price] * n,
            "open": [price] * n,
        }
    )


def test_fet_config_has_atr_multiplier() -> None:
    cfg = get_coin_config("FETUSDT")
    assert cfg.get("atr_multiplier") == pytest.approx(1.0)


def test_evaluate_stop_loss_reject_reason_wrong_side_long() -> None:
    strat = LiquiditySweepReversalBase()
    df = _flat_15m(1.0, 30)
    entry = 1.0
    anchor = 1.05
    _sl, _dist, reason = strat._evaluate_stop_loss(entry, "LONG", df, anchor)
    assert reason is not None
    assert "stop at or above entry" in reason


def test_evaluate_stop_loss_reject_reason_distance_too_wide() -> None:
    strat = LiquiditySweepReversalBase()
    price = 100.0
    df = pd.DataFrame(
        {
            "high": [price * 1.05] * 30,
            "low": [price * 0.95] * 30,
            "close": [price] * 30,
            "open": [price] * 30,
        }
    )
    entry = 100.0
    anchor = 80.0
    _sl, _dist, reason = strat._evaluate_stop_loss(entry, "LONG", df, anchor)
    assert reason is not None
    assert "exceeds max" in reason


def test_coin_atr_multiplier_tightens_liquidity_stop() -> None:
    strat = LiquiditySweepReversalBase()
    df = _flat_15m(0.27, 30)
    entry = 0.2727
    anchor = 0.273
    default_sl = strat.get_stop_loss(entry, "SHORT", df, anchor, atr_multiplier=1.0)
    fet_sl = strat.get_stop_loss(entry, "SHORT", df, anchor, atr_multiplier=0.5)
    assert default_sl is not None
    assert fet_sl is not None
    assert fet_sl[1] < default_sl[1]
    assert fet_sl[0] < default_sl[0]
