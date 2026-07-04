"""Unit tests for ``monitoring.risk_limit_tracking``."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.unit


@pytest.fixture
def rt_mod(tmp_path, monkeypatch):
    monkeypatch.setenv("RISK_LIMIT_TRACKING_PATH", str(tmp_path / "risk_limit_tracking.json"))
    monkeypatch.setenv("PERFORMANCE_DIR", str(tmp_path / "performance"))
    from monitoring import risk_limit_tracking as m

    return m


def test_ensure_today_creates_file(rt_mod, tmp_path) -> None:
    row = rt_mod.ensure_today(balance_usdt=1000.5)
    assert row["date"] == rt_mod._utc_date_iso()
    assert row["starting_balance"] == 1000.5
    assert row["ending_balance"] == 1000.5
    assert row["daily_pnl"] == 0.0
    assert row["total_trade"] == 0
    p = tmp_path / "risk_limit_tracking.json"
    assert p.exists()
    month_files = list((tmp_path / "performance").glob("*_statistics.json"))
    assert len(month_files) == 1


def test_record_new_open_increments_total_trade(rt_mod) -> None:
    rt_mod.ensure_today(balance_usdt=500.0)
    rt_mod.record_new_open(balance_usdt=500.0)
    rt_mod.record_new_open(balance_usdt=499.0)
    path = rt_mod.tracking_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["total_trade"] == 2


def test_close_updates_pnl_and_stops_at_max_losses(rt_mod) -> None:
    rt_mod.ensure_today(balance_usdt=1000.0)
    for _ in range(3):
        rt_mod.record_full_position_close(
            exchange_pnl_usdt=-10.0,
            internal_realized_pnl_usdt=-10.0,
            journal_balance_usdt=990.0,
            max_losses_per_day=3,
        )
    data = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert data["loss"] == 3
    assert data["win"] == 0
    assert data["daily_pnl"] == -30.0
    assert data["trading_stopped"] is True
    assert rt_mod.risk_file_allows_new_entries(balance_usdt=990.0) is False


def test_notify_performance_snapshot_after_close_sends_day_stats(rt_mod, monkeypatch) -> None:
    sent: list[tuple[dict, str]] = []

    def _fake_send(snap: dict, *, heading: str = "DAILY PERFORMANCE") -> bool:
        sent.append((dict(snap), heading))
        return True

    monkeypatch.setattr(rt_mod.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(rt_mod.settings, "PERFORMANCE_SNAPSHOT_ON_CLOSE", True, raising=False)
    monkeypatch.setattr(rt_mod.settings, "DAILY_PERFORMANCE_TELEGRAM", True, raising=False)
    monkeypatch.setattr("monitoring.notifier.send_daily_performance_snapshot_alert", _fake_send)

    rt_mod.record_new_open(balance_usdt=100.0)
    rt_mod.record_full_position_close(
        exchange_pnl_usdt=2.5,
        internal_realized_pnl_usdt=2.5,
        journal_balance_usdt=102.5,
        open_positions=0,
    )
    rt_mod.notify_performance_snapshot_after_close(open_positions=0)
    assert len(sent) == 1
    assert sent[0][1] == "RUNTIME PERFORMANCE"
    assert sent[0][0]["daily_pnl"] == 2.5
    assert sent[0][0]["open"] == 0


def test_close_prefers_exchange_pnl_for_win_loss(rt_mod) -> None:
    rt_mod.ensure_today(balance_usdt=1000.0)
    rt_mod.record_full_position_close(
        exchange_pnl_usdt=5.25,
        internal_realized_pnl_usdt=-99.0,
        journal_balance_usdt=1005.25,
        max_losses_per_day=3,
    )
    data = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert data["win"] == 1
    assert data["loss"] == 0
    assert data["daily_pnl"] == 5.25


def test_rollover_resets_for_new_utc_date(rt_mod, tmp_path) -> None:
    path = rt_mod.tracking_path()
    path.write_text(
        json.dumps(
            {
                "date": "1999-01-01",
                "starting_balance": 1.0,
                "ending_balance": 1.0,
                "daily_pnl": 3.0,
                "daily_pnl_percent": 300.0,
                "total_trade": 9,
                "win": 1,
                "loss": 2,
                "max_drawdown_percent": 0.0,
                "trading_stopped": True,
                "peak_balance": 1.0,
            }
        ),
        encoding="utf-8",
    )
    with patch.object(rt_mod, "_utc_date_iso", return_value="2026-06-01"):
        row = rt_mod.ensure_today(balance_usdt=2500.75)
    assert row["date"] == "2026-06-01"
    assert row["starting_balance"] == 2500.75
    assert row["total_trade"] == 0
    assert row["trading_stopped"] is False


def test_legacy_total_pnl_migrates(rt_mod, monkeypatch) -> None:
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2026-05-13")
    rt_mod.tracking_path().write_text(
        json.dumps(
            {
                "date": "2026-05-13",
                "starting_balance": 1000.0,
                "current_balance": 900.0,
                "total_trade": 0,
                "win": 0,
                "loss": 0,
                "total_pnl": -50.0,
                "trading_stopped": False,
            }
        ),
        encoding="utf-8",
    )
    row = rt_mod.ensure_today(balance_usdt=900.0)
    assert row["daily_pnl"] == -50.0
    assert row["ending_balance"] == 900.0


def test_max_daily_loss_sets_trading_stopped(rt_mod, monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "MAX_DAILY_LOSS", 0.05, raising=False)
    rt_mod.ensure_today(balance_usdt=1000.0)
    rt_mod.record_full_position_close(
        exchange_pnl_usdt=-60.0,
        internal_realized_pnl_usdt=-60.0,
        journal_balance_usdt=940.0,
        max_losses_per_day=99,
    )
    data = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert data["daily_pnl"] == -60.0
    assert data["trading_stopped"] is True
    assert rt_mod.risk_file_allows_new_entries(balance_usdt=940.0) is False


def test_allows_false_when_file_breaches_max_daily_loss_without_flag(rt_mod, monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "MAX_DAILY_LOSS", 0.06, raising=False)
    rt_mod.tracking_path().write_text(
        json.dumps(
            {
                "date": rt_mod._utc_date_iso(),
                "starting_balance": 1000.0,
                "ending_balance": 900.0,
                "daily_pnl": -70.0,
                "daily_pnl_percent": -7.0,
                "total_trade": 2,
                "win": 0,
                "loss": 2,
                "max_drawdown_percent": 0.0,
                "trading_stopped": False,
                "peak_balance": 1000.0,
            }
        ),
        encoding="utf-8",
    )
    assert rt_mod.risk_file_allows_new_entries(balance_usdt=900.0) is False
    data = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert data["trading_stopped"] is True


def test_max_trades_per_day_blocks_and_sets_flag(rt_mod, monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "MAX_TRADES_PER_DAY", 3, raising=False)
    rt_mod.ensure_today(balance_usdt=1000.0)
    rt_mod.record_new_open(balance_usdt=1000.0)
    rt_mod.record_new_open(balance_usdt=1000.0)
    assert rt_mod.risk_file_allows_new_entries(balance_usdt=1000.0) is True
    rt_mod.record_new_open(balance_usdt=1000.0)
    assert int(json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))["total_trade"]) == 3
    assert rt_mod.risk_file_allows_new_entries(balance_usdt=1000.0) is False
    data = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert data["trading_stopped"] is True


def test_entry_gate_returns_short_reasons(rt_mod, monkeypatch) -> None:
    from config import settings

    monkeypatch.setattr(settings, "MAX_TRADES_PER_DAY", 2, raising=False)
    monkeypatch.setattr(settings, "MAX_LOSSES_PER_DAY", 2, raising=False)
    monkeypatch.setattr(settings, "MAX_DAILY_LOSS", 0.05, raising=False)
    rt_mod.ensure_today(balance_usdt=1000.0)
    ok, reason = rt_mod.risk_file_entry_gate(balance_usdt=1000.0)
    assert ok and reason is None
    rt_mod.record_new_open(balance_usdt=1000.0)
    rt_mod.record_new_open(balance_usdt=1000.0)
    ok, reason = rt_mod.risk_file_entry_gate(balance_usdt=1000.0)
    assert not ok and reason == "Exceed Total trade"


def test_upsert_performance_snapshot_direct(rt_mod, tmp_path) -> None:
    rt_mod.upsert_performance_snapshot(
        {
            "date": "2026-04-01",
            "starting_balance": 500.0,
            "ending_balance": 510.0,
            "daily_pnl": 10.0,
            "daily_pnl_percent": 2.0,
            "total_trade": 1,
            "win": 1,
            "loss": 0,
            "open": 0,
            "max_drawdown_percent": 0.5,
            "peak_balance": 510.0,
            "trading_stopped": False,
        }
    )
    perf = rt_mod.performance_dir() / "04-2026_statistics.json"
    assert perf.exists()
    month = json.loads(perf.read_text(encoding="utf-8"))
    assert month["month"] == "2026-04"
    assert month["days"][0]["daily_pnl"] == 10.0


def test_upsert_performance_snapshot_recover_empty_month_file(rt_mod, tmp_path) -> None:
    """Empty or corrupt month files must not block further upserts (JSONDecodeError trap)."""
    perf = rt_mod.performance_dir() / "05-2026_statistics.json"
    perf.parent.mkdir(parents=True, exist_ok=True)
    perf.write_text("", encoding="utf-8")
    rt_mod.upsert_performance_snapshot(
        {
            "date": "2026-05-12",
            "starting_balance": 1000.0,
            "ending_balance": 1001.0,
            "daily_pnl": 1.0,
            "daily_pnl_percent": 0.1,
            "total_trade": 0,
            "win": 0,
            "loss": 0,
            "open": 0,
            "max_drawdown_percent": 0.0,
            "peak_balance": 1001.0,
            "trading_stopped": False,
        }
    )
    month = json.loads(perf.read_text(encoding="utf-8"))
    assert month["month"] == "2026-05"
    assert len(month["days"]) == 1
    assert month["days"][0]["date"] == "2026-05-12"


def test_notify_monthly_cumulative_telegram(rt_mod, monkeypatch) -> None:
    sent: list[tuple[dict, str]] = []

    def _fake_send(snap, *, heading="DAILY PERFORMANCE", **kwargs):
        sent.append((snap, heading))
        return True

    monkeypatch.setattr(rt_mod.settings, "MODE", "demo", raising=False)
    monkeypatch.setattr(rt_mod.settings, "MONTHLY_CUMULATIVE_TELEGRAM", True, raising=False)
    monkeypatch.setattr(rt_mod.settings, "DAILY_PERFORMANCE_TELEGRAM", False, raising=False)
    monkeypatch.setattr("monitoring.notifier.send_daily_performance_snapshot_alert", _fake_send)

    rt_mod.upsert_performance_snapshot(
        {
            "date": "2026-05-18",
            "starting_balance": 100.0,
            "ending_balance": 105.0,
            "daily_pnl": 5.0,
            "daily_pnl_percent": 5.0,
            "total_trade": 2,
            "win": 2,
            "loss": 0,
            "open": 0,
            "max_drawdown_percent": 0.5,
            "peak_balance": 105.0,
            "trading_stopped": False,
        }
    )
    rt_mod.notify_monthly_cumulative_telegram("2026-05-18", open_count=1)
    assert len(sent) == 1
    assert sent[0][1] == "MONTHLY PERFORMANCE"
    assert sent[0][0]["daily_pnl"] == 5.0
    assert sent[0][0]["open"] == 1


def test_read_day_snapshot_for_date(rt_mod) -> None:
    rt_mod.upsert_performance_snapshot(
        {
            "date": "2026-06-01",
            "starting_balance": 100.0,
            "ending_balance": 101.0,
            "daily_pnl": 1.0,
            "daily_pnl_percent": 1.0,
            "total_trade": 2,
            "win": 1,
            "loss": 1,
            "open": 1,
            "max_drawdown_percent": 0.1,
            "peak_balance": 101.0,
            "trading_stopped": False,
        }
    )
    rt_mod.upsert_performance_snapshot(
        {
            "date": "2026-06-02",
            "starting_balance": 101.0,
            "ending_balance": 101.0,
            "daily_pnl": 0.0,
            "daily_pnl_percent": 0.0,
            "total_trade": 0,
            "win": 0,
            "loss": 0,
            "open": 0,
            "max_drawdown_percent": 0.0,
            "peak_balance": 101.0,
            "trading_stopped": False,
        }
    )
    snap = rt_mod.read_day_snapshot_for_date("2026-06-01")
    assert snap is not None
    assert snap["date"] == "2026-06-01"
    assert snap["total_trade"] == 2
    assert snap["open"] == 1
    assert rt_mod.read_day_snapshot_for_date("2099-13-40") is None


def test_read_day_snapshot_legacy_missing_open_defaults_zero(rt_mod, tmp_path) -> None:
    perf = rt_mod.performance_dir() / "05-2026_statistics.json"
    perf.parent.mkdir(parents=True, exist_ok=True)
    perf.write_text(
        json.dumps(
            {
                "month": "2026-05",
                "days": [
                    {
                        "date": "2026-05-04",
                        "starting_balance": 100.0,
                        "ending_balance": 98.91,
                        "daily_pnl": -1.09,
                        "daily_pnl_percent": -1.09,
                        "total_trade": 3,
                        "win": 1,
                        "loss": 1,
                        "max_drawdown_percent": 1.93,
                        "trading_stopped": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    snap = rt_mod.read_day_snapshot_for_date("2026-05-04")
    assert snap is not None
    assert snap["open"] == 0
    assert snap["peak_balance"] == 100.0


def test_ensure_today_flushes_completed_day_to_performance(rt_mod, monkeypatch) -> None:
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2026-05-10")
    rt_mod.ensure_today(balance_usdt=1000.0)
    rt_mod.record_new_open(balance_usdt=1000.0)
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2026-05-11")
    rt_mod.ensure_today(balance_usdt=1005.0)
    snap = rt_mod.read_day_snapshot_for_date("2026-05-10")
    assert snap is not None
    assert snap["total_trade"] == 1
    assert snap["open"] == 0
    row = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert row["date"] == "2026-05-11"


def test_ensure_today_open_at_eod_on_rollover(rt_mod, monkeypatch) -> None:
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2026-05-04")
    rt_mod.ensure_today(balance_usdt=100.0)
    rt_mod.record_new_open(balance_usdt=100.0)
    rt_mod.record_new_open(balance_usdt=100.0)
    rt_mod.record_new_open(balance_usdt=100.0)
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2026-05-05")
    rt_mod.ensure_today(balance_usdt=98.91, open_at_eod=1)
    snap = rt_mod.read_day_snapshot_for_date("2026-05-04")
    assert snap is not None
    assert snap["total_trade"] == 3
    assert snap["open"] == 1


def test_monthly_snapshot_has_export_keys_only(rt_mod, monkeypatch) -> None:
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2026-05-13")
    rt_mod.ensure_today(balance_usdt=1000.0)
    rt_mod.record_full_position_close(
        exchange_pnl_usdt=-0.33,
        internal_realized_pnl_usdt=-0.33,
        journal_balance_usdt=999.67,
        max_losses_per_day=99,
    )
    perf = rt_mod.performance_dir() / "05-2026_statistics.json"
    assert perf.exists()
    month = json.loads(perf.read_text(encoding="utf-8"))
    assert month["month"] == "2026-05"
    assert len(month["days"]) == 1
    day = month["days"][0]
    assert set(day.keys()) == set(rt_mod.SNAPSHOT_EXPORT_KEYS)
    assert day["peak_balance"] == 1000.0
    assert day["date"] == "2026-05-13"
    assert day["daily_pnl"] == -0.33


def test_atomic_write_concurrent_threads(rt_mod) -> None:
    """Regression: fixed ``*.tmp`` name raced when multiple writers used the same path."""
    import threading

    path = rt_mod.tracking_path()
    errors: list[BaseException] = []

    def _writer(n: int) -> None:
        try:
            rt_mod._atomic_write(path, {"date": "2026-01-01", "n": n})
        except BaseException as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "date" in data


def test_sim_date_iso_skips_performance_month_file(rt_mod, tmp_path, monkeypatch) -> None:
    """Backtest passes ``sim_date_iso`` so ``performance/`` is not touched each write."""
    monkeypatch.setattr(rt_mod, "_utc_date_iso", lambda: "2099-12-01")
    rt_mod.record_new_open(balance_usdt=1000.0, sim_date_iso="2026-01-15")
    data = json.loads(rt_mod.tracking_path().read_text(encoding="utf-8"))
    assert data["date"] == "2026-01-15"
    assert data["total_trade"] == 1
    assert list((tmp_path / "performance").glob("*_statistics.json")) == []
