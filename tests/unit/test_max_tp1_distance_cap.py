from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.coins.loader import get_coin_config, resolve_max_tp1_distance
from strategy.tp_structure_targets import (
    clamp_tp1_to_max_distance,
    resolve_tp1_price,
    tp1_distance_frac,
)


def test_fet_config_has_no_max_tp1_pct() -> None:
    cfg = get_coin_config("FETUSDT")
    assert cfg.get("max_tp1_pct") is None
    assert resolve_max_tp1_distance(cfg) is None


def test_clamp_tp1_short() -> None:
    entry = 0.2727
    tp1_wide = entry * (1.0 - 0.0343)
    tp1 = clamp_tp1_to_max_distance(
        entry=entry,
        direction="SHORT",
        tp1=tp1_wide,
        max_tp1_distance=0.025,
    )
    assert tp1_distance_frac(entry=entry, direction="SHORT", tp1=tp1) == pytest.approx(0.025)
    assert tp1 == pytest.approx(entry * 0.975)


def test_resolve_tp1_price_applies_cap() -> None:
    entry = 0.2727
    dist = 0.0343
    tp1 = resolve_tp1_price(
        entry=entry,
        direction="SHORT",
        dist=dist,
        tp1_r=1.0,
        max_tp1_distance=0.015,
    )
    assert tp1_distance_frac(entry=entry, direction="SHORT", tp1=tp1) == pytest.approx(0.015)
