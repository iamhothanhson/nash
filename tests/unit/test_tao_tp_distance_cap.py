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

from app.coins.loader import get_coin_config, resolve_max_tp1_distance, resolve_max_tp2_distance
from strategy.tp_structure_targets import (
    resolve_tp1_price,
    resolve_tp1_tp2_prices,
    resolve_tp2_price,
    tp1_distance_frac,
)

pytestmark = pytest.mark.unit


def test_tao_config_has_no_tp_pct_caps() -> None:
    cfg = get_coin_config("TAOUSDT")
    assert cfg.get("max_tp1_pct") is None
    assert cfg.get("max_tp2_pct") is None
    assert resolve_max_tp1_distance(cfg) is None
    assert resolve_max_tp2_distance(cfg) is None


def test_tao_caps_tp1_at_1_5_pct_when_r_wider() -> None:
    entry = 250.0
    dist = 0.03
    tp1 = resolve_tp1_price(
        entry=entry,
        direction="LONG",
        dist=dist,
        tp1_r=1.0,
        max_tp1_distance=0.015,
    )
    assert tp1_distance_frac(entry=entry, direction="LONG", tp1=tp1) == pytest.approx(0.015)


def test_tao_caps_tp2_at_2_5_pct_when_r_wider() -> None:
    entry = 250.0
    dist = 0.04
    tp2 = resolve_tp2_price(
        entry=entry,
        direction="LONG",
        dist=dist,
        tp2_r=2.0,
        max_tp2_distance=0.025,
    )
    assert tp1_distance_frac(entry=entry, direction="LONG", tp1=tp2) == pytest.approx(0.025)


def test_tao_keeps_1r_tp1_when_within_cap() -> None:
    entry = 250.0
    cfg = get_coin_config("TAOUSDT")
    dist = 0.01
    tp1, _tp2 = resolve_tp1_tp2_prices(
        entry=entry,
        direction="LONG",
        dist=dist,
        data_15m=pd.DataFrame(),
        cfg=cfg,
        tp1_r=1.0,
        tp2_r=2.0,
    )
    expected = resolve_tp1_price(
        entry=entry,
        direction="LONG",
        dist=dist,
        tp1_r=1.0,
    )
    assert tp1 == pytest.approx(expected)
