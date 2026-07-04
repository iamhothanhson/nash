from __future__ import annotations

import sys
from pathlib import Path

_PROJECT = Path(__file__).resolve().parents[2]
_APP = _PROJECT / "app"
for _p in (_PROJECT, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from app.position_management import hard_stop
from app.position_management.staged import ManagedPosition


def _pos(**kwargs: object) -> ManagedPosition:
    defaults: dict[str, object] = {
        "symbol": "TAOUSDT",
        "direction": "LONG",
        "qty_total": 1.0,
        "qty_open": 1.0,
        "entry": 100.0,
        "stop_loss": 99.0,
        "tp1": 101.0,
        "tp2": 102.0,
        "tp3": 103.0,
        "initial_risk_usd": 1.0,
        "max_hard_stop_loss_usd": 1.0,
    }
    defaults.update(kwargs)
    return ManagedPosition(**defaults)  # type: ignore[arg-type]


def test_planned_max_loss_matches_notional_times_sl_frac() -> None:
    assert abs(hard_stop.planned_max_loss_usd(1000.0, 100.0, 99.0) - 10.0) < 1e-9


def test_max_loss_allowed_scales_with_open_fraction() -> None:
    p = _pos(qty_total=2.0, qty_open=1.0, max_hard_stop_loss_usd=10.0)
    assert abs(hard_stop.max_loss_allowed(p) - 5.0) < 1e-9


def test_check_hard_stop_false_when_under_cap() -> None:
    p = _pos()
    assert not hard_stop.check_hard_stop(p, -0.5)


def test_check_hard_stop_true_at_cap() -> None:
    p = _pos()
    assert hard_stop.check_hard_stop(p, -1.0)


def test_check_hard_stop_disabled_when_no_cap() -> None:
    p = _pos(initial_risk_usd=0.0, max_hard_stop_loss_usd=0.0)
    assert not hard_stop.check_hard_stop(p, -1e6)


def test_hit_stop_price_long() -> None:
    p = _pos(direction="LONG", entry=100.0, stop_loss=99.0, current_stop_loss=99.0)
    hit, px = hard_stop.hit_stop_price(pos=p, mark_price=98.9, stop_buffer_frac=0.0)
    assert hit
    assert abs(px - 98.9) < 1e-9


def test_hit_stop_price_short() -> None:
    p = _pos(direction="SHORT", entry=100.0, stop_loss=101.0, current_stop_loss=101.0)
    hit, px = hard_stop.hit_stop_price(pos=p, mark_price=101.2, stop_buffer_frac=0.0)
    assert hit
    assert abs(px - 101.2) < 1e-9


def test_evaluate_hard_stop_price_trigger() -> None:
    p = _pos(direction="LONG", entry=100.0, stop_loss=99.0, current_stop_loss=99.0)
    d = hard_stop.evaluate_hard_stop(
        pos=p,
        mark_price=98.8,
        exchange_sl_active=False,
    )
    assert d.triggered
    assert d.reason == "hard_stop_price_trigger"


def test_price_trigger_suppressed_on_runner_by_default() -> None:
    p = _pos(hit_tp2=True, tp2_hit_at_ts=1000.0)
    assert hard_stop.price_trigger_suppressed_after_tp2(
        p,
        wall_ts=2000.0,
        closed_bar_ts=1500.0,
        grace_sec=0.0,
        skip_same_bar=False,
    )


def test_price_trigger_suppressed_after_tp2_grace(monkeypatch) -> None:
    monkeypatch.setattr(
        "position_management.hard_stop.settings.HARD_STOP_DISABLE_PRICE_ON_RUNNER",
        False,
    )
    p = _pos(hit_tp2=True, tp2_hit_at_ts=1000.0)
    assert hard_stop.price_trigger_suppressed_after_tp2(
        p,
        wall_ts=1040.0,
        closed_bar_ts=1000.0,
        grace_sec=90.0,
        skip_same_bar=True,
    )
    assert not hard_stop.price_trigger_suppressed_after_tp2(
        p,
        wall_ts=1091.0,
        closed_bar_ts=1300.0,
        grace_sec=90.0,
        skip_same_bar=True,
    )


def test_evaluate_hard_stop_exchange_sl_active() -> None:
    p = _pos(direction="LONG", entry=100.0, stop_loss=99.0, current_stop_loss=99.0)
    d = hard_stop.evaluate_hard_stop(
        pos=p,
        mark_price=95.0,
        exchange_sl_active=True,
    )
    assert not d.triggered
    assert d.reason == "exchange_sl_active"


def test_evaluate_hard_stop_holds_when_mark_above_stop() -> None:
    p = _pos(direction="LONG", entry=100.0, stop_loss=99.0, current_stop_loss=99.0)
    d = hard_stop.evaluate_hard_stop(
        pos=p,
        mark_price=99.5,
        exchange_sl_active=False,
    )
    assert not d.triggered
    assert d.reason == "hold"
