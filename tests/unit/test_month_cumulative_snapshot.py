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

pytestmark = pytest.mark.unit


@pytest.fixture
def rt_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("RISK_LIMIT_TRACKING_PATH", str(tmp_path / "risk_limit_tracking.json"))
    monkeypatch.setenv("PERFORMANCE_DIR", str(tmp_path / "performance"))
    from monitoring import risk_limit_tracking as m

    return m


def _upsert_day(rt_mod, *, date: str, start: float, end: float, pnl: float, trades: int, wins: int, losses: int) -> None:
    rt_mod.upsert_performance_snapshot(
        {
            "date": date,
            "starting_balance": start,
            "ending_balance": end,
            "daily_pnl": pnl,
            "daily_pnl_percent": 100.0 * pnl / start if start else 0.0,
            "total_trade": trades,
            "win": wins,
            "loss": losses,
            "open": 0,
            "max_drawdown_percent": 1.0,
            "peak_balance": max(start, end),
            "trading_stopped": False,
        }
    )


def test_build_month_cumulative_snapshot_mtd(rt_mod, tmp_path) -> None:
    _upsert_day(rt_mod, date="2026-05-01", start=100.0, end=102.0, pnl=2.0, trades=1, wins=1, losses=0)
    _upsert_day(rt_mod, date="2026-05-02", start=102.0, end=105.0, pnl=3.0, trades=2, wins=1, losses=1)
    _upsert_day(rt_mod, date="2026-05-03", start=105.0, end=106.5, pnl=1.5, trades=1, wins=1, losses=0)

    snap = rt_mod.build_month_cumulative_snapshot("2026-05-03")
    assert snap is not None
    assert snap["date"] == "2026-05-03"
    assert snap["starting_balance"] == 100.0
    assert snap["ending_balance"] == 106.5
    assert snap["daily_pnl"] == pytest.approx(6.5)
    assert snap["daily_pnl_percent"] == pytest.approx(6.5)
    assert snap["total_trade"] == 4
    assert snap["win"] == 3
    assert snap["loss"] == 1
    assert snap["peak_balance"] == pytest.approx(106.5)


def test_build_month_cumulative_excludes_future_days(rt_mod, tmp_path) -> None:
    _upsert_day(rt_mod, date="2026-05-10", start=100.0, end=101.0, pnl=1.0, trades=1, wins=1, losses=0)
    _upsert_day(rt_mod, date="2026-05-12", start=101.0, end=103.0, pnl=2.0, trades=1, wins=1, losses=0)

    snap = rt_mod.build_month_cumulative_snapshot("2026-05-10")
    assert snap is not None
    assert snap["daily_pnl"] == pytest.approx(1.0)
    assert snap["ending_balance"] == pytest.approx(101.0)
