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

from app.coins.loader import (
    coin_enforces_min_risk_reward,
    coin_uses_structure_tp,
    get_coin_config,
    passes_coin_execution_gates,
    resolve_max_tp2_distance,
)
from strategy.tp_structure_targets import (
    resolve_tp1_price,
    resolve_tp1_tp2_prices,
    resolve_tp2_price,
    tp1_distance_frac,
)


def test_fet_config_has_no_tp_pct_caps() -> None:
    cfg = get_coin_config("FETUSDT")
    assert cfg.get("max_tp2_pct") is None
    assert resolve_max_tp2_distance(cfg) is None


def test_fet_caps_tp2_at_2_5_pct_when_r_wider() -> None:
    entry = 0.2727
    dist = 0.05
    tp2 = resolve_tp2_price(
        entry=entry,
        direction="SHORT",
        dist=dist,
        tp2_r=2.0,
        max_tp2_distance=0.025,
    )
    assert tp1_distance_frac(entry=entry, direction="SHORT", tp1=tp2) == pytest.approx(0.025)


def test_fet_caps_tp1_at_1_5_pct_when_r_wider() -> None:
    entry = 0.2727
    dist = 0.034
    tp1 = resolve_tp1_price(
        entry=entry,
        direction="SHORT",
        dist=dist,
        tp1_r=1.0,
        max_tp1_distance=0.015,
    )
    assert tp1_distance_frac(entry=entry, direction="SHORT", tp1=tp1) == pytest.approx(0.015)
    uncapped = resolve_tp1_price(
        entry=entry, direction="SHORT", dist=dist, tp1_r=1.0, max_tp1_distance=None
    )
    assert tp1_distance_frac(entry=entry, direction="SHORT", tp1=uncapped) > 0.015


def test_fet_keeps_1r_tp1_when_within_cap() -> None:
    entry = 0.2727
    dist = 0.012
    tp1, _tp2 = resolve_tp1_tp2_prices(
        entry=entry,
        direction="SHORT",
        dist=dist,
        data_15m=pd.DataFrame(),
        cfg=None,
        tp1_r=1.0,
        tp2_r=2.0,
    )
    expected = resolve_tp1_price(
        entry=entry,
        direction="SHORT",
        dist=dist,
        tp1_r=1.0,
    )
    assert tp1 == pytest.approx(expected)


def test_fet_skips_min_risk_reward_gate() -> None:
    cfg = get_coin_config("FETUSDT")
    assert coin_enforces_min_risk_reward(cfg) is False
    assert coin_uses_structure_tp(cfg) is False
    gate = {
        "symbol": "FETUSDT",
        "entry": 0.2727,
        "stop_loss": 0.2821,
        "tp1": 0.2659,
        "setup_score": 10,
        "setup_grade": "A",
        "confirmation_mode": "confirmed",
    }
    rr = abs(gate["tp1"] - gate["entry"]) / abs(gate["entry"] - gate["stop_loss"])
    assert rr < 1.0
    assert passes_coin_execution_gates(gate) is True
