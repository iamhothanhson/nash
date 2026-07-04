from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import app.monitoring.position_journal as position_journal
from app.monitoring.position_journal import log_position_open, update_open_position_journal


class TestUpdateOpenPositionJournal:
    def setup_method(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_repo_root = position_journal._repo_root
        position_journal._repo_root = lambda: self.tmp_path

    def teardown_method(self) -> None:
        position_journal._repo_root = self.old_repo_root
        self.tmp.cleanup()

    def _read_month(self, month: str) -> list[dict]:
        yyyy, mm = month.split("-")
        path = self.tmp_path / "position_history" / f"{mm}-{yyyy}-positions-history.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_tp1_and_breakeven_update_open_row(self) -> None:
        t_open = datetime(2026, 5, 30, 8, 0, 0, tzinfo=timezone.utc).isoformat()
        t_tp1 = datetime(2026, 5, 30, 11, 10, 2, tzinfo=timezone.utc).isoformat()
        log_position_open(
            time_iso=t_open,
            symbol="TAOUSDT",
            direction="SHORT",
            entry=251.75,
            stop_loss=254.0,
            tp1=248.53,
            tp2=245.0,
            tp3=0.0,
            size_usdt=10.07,
            leverage=10,
            risk_usdt=0.09,
            partial_close=[0.5, 0.3, 0.2],
        )
        assert update_open_position_journal(
            time_iso=t_tp1,
            symbol="TAOUSDT",
            direction="SHORT",
            open_time_iso=t_open,
            entry=251.75,
            qty_total=0.04,
            leverage=10,
            tp1_hit=True,
            stop_loss_price=251.75,
            risk_usdt=0.0,
        )
        row = self._read_month("2026-05")[0]
        assert row["status"] == "Open"
        assert row["closed"] is None
        assert row["take_profit"][0]["tp1_hit"] is True
        assert row["stop_loss"]["price"] == 251.75
        assert float(row["stop_loss"]["risk_usdt"]) == 0.0
        assert "sl_order_id" in row["stop_loss"]
        assert "tp1_order_id" in row["take_profit"][0]

    def test_tp1_hit_preserves_existing_tp1_order_id(self) -> None:
        t_open = datetime(2026, 5, 30, 8, 0, 0, tzinfo=timezone.utc).isoformat()
        t_tp1 = datetime(2026, 5, 30, 11, 10, 2, tzinfo=timezone.utc).isoformat()
        log_position_open(
            time_iso=t_open,
            symbol="FETUSDT",
            direction="SHORT",
            entry=0.2057,
            stop_loss=0.2080,
            tp1=0.2037,
            tp2=0.2020,
            tp3=0.0,
            size_usdt=10.0,
            leverage=10,
            risk_usdt=0.11,
            partial_close=[0.5, 0.3, 0.2],
            tp1_order_id=11457736270,
        )
        assert update_open_position_journal(
            time_iso=t_tp1,
            symbol="FETUSDT",
            direction="SHORT",
            open_time_iso=t_open,
            entry=0.2057,
            qty_total=0.04,
            leverage=10,
            tp1_hit=True,
            stop_loss_price=0.2055,
            risk_usdt=0.0,
            exchange_order_ids={
                "sl_order_id": None,
                "tp1_order_id": None,
                "tp2_order_id": None,
                "tp3_order_id": None,
            },
        )
        row = self._read_month("2026-05")[0]
        assert row["take_profit"][0]["tp1_hit"] is True
        assert row["take_profit"][0]["tp1_order_id"] == 11457736270

    def test_log_open_includes_exchange_order_ids(self) -> None:
        t_open = datetime(2026, 5, 30, 8, 0, 0, tzinfo=timezone.utc).isoformat()
        log_position_open(
            time_iso=t_open,
            symbol="TAOUSDT",
            direction="SHORT",
            entry=251.75,
            stop_loss=254.0,
            tp1=248.53,
            tp2=245.0,
            tp3=0.0,
            size_usdt=10.07,
            leverage=10,
            risk_usdt=0.09,
            partial_close=[0.5, 0.3, 0.2],
            sl_order_id=1001,
            tp1_order_id=2001,
            tp2_order_id=None,
            tp3_order_id=None,
        )
        row = self._read_month("2026-05")[0]
        assert row["stop_loss"]["sl_order_id"] == 1001
        assert row["take_profit"][0]["tp1_order_id"] == 2001
        assert row["take_profit"][1]["tp2_order_id"] is None
        assert row["take_profit"][2]["tp3_order_id"] is None

    def test_close_merges_by_open_time_when_entry_differs(self) -> None:
        t_open = datetime(2026, 5, 30, 8, 0, 0, tzinfo=timezone.utc).isoformat()
        t_close = datetime(2026, 5, 30, 10, 0, 0, tzinfo=timezone.utc).isoformat()
        log_position_open(
            time_iso=t_open,
            symbol="FETUSDT",
            direction="SHORT",
            entry=0.2700,
            stop_loss=0.2800,
            tp1=0.2630,
            tp2=0.2600,
            tp3=0.2550,
            size_usdt=5.18,
            leverage=10,
            risk_usdt=0.19,
            partial_close=[0.5, 0.3, 0.2],
        )
        from app.monitoring.position_journal import log_position_closed

        log_position_closed(
            time_iso=t_close,
            symbol="FETUSDT",
            direction="SHORT",
            open_time_iso=t_open,
            entry=0.2727,
            stop_loss=0.2800,
            tp1=0.2630,
            tp2=0.2600,
            tp3=0.2550,
            qty_total=19.0,
            leverage=10,
            risk_usdt=0.19,
            pnl_usdt=0.42,
            balance_usdt=100.42,
            closed_reason="SL HIT",
        )
        rows = self._read_month("2026-05")
        assert len(rows) == 1
        assert rows[0]["status"] == "Closed"
        assert rows[0]["entry"] == 0.2727
        assert rows[0]["opened"] == "May-30-2026 08:00:00"

    def test_fet_journal_preserves_four_decimal_prices(self) -> None:
        t_open = datetime(2026, 6, 3, 3, 40, 30, tzinfo=timezone.utc).isoformat()
        log_position_open(
            time_iso=t_open,
            symbol="FETUSDT",
            direction="SHORT",
            entry=0.2515,
            stop_loss=0.2548,
            tp1=0.2477,
            tp2=0.2439,
            tp3=0.0,
            size_usdt=3155.57,
            leverage=10,
            risk_usdt=41.73,
            partial_close=[0.5, 0.3, 0.2],
        )
        row = self._read_month("2026-06")[0]
        assert row["entry"] == 0.2515
        assert row["stop_loss"]["price"] == 0.2548
        assert row["take_profit"][0]["price"] == 0.2477
        assert row["take_profit"][1]["price"] == 0.2439
        assert row["take_profit"][2]["price"] == 0.0
