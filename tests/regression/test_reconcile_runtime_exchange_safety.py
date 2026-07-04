from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import main
from app.config import settings
from app.position_management.staged import ManagedPosition


class _Client:
    def __init__(self, snapshots: dict[str, dict[str, float]]):
        self._snapshots = snapshots

    def get_position_risk_snapshot(self, symbol: str) -> dict[str, float]:
        return self._snapshots.get(symbol, {"position_amt": 0.0, "entry_price": 0.0})


class TestReconcileRuntimeExchangeSafetyRegression:
    def setup_method(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_cwd = Path.cwd()
        self.originals = {
            "MODE": settings.MODE,
            "SYMBOLS": settings.SYMBOLS,
            "ALLOWED_SYMBOLS": settings.ALLOWED_SYMBOLS,
            "PROJECT_ROOT": main.PROJECT_ROOT,
            "APP_PATH": main.APP_PATH,
        }
        settings.MODE = "live"
        settings.SYMBOLS = ["TAOUSDT"]
        settings.ALLOWED_SYMBOLS = ["TAOUSDT"]
        main.PROJECT_ROOT = self.tmp_path
        main.APP_PATH = self.tmp_path / "app"
        os.chdir(self.tmp_path)

    def teardown_method(self) -> None:
        os.chdir(self.old_cwd)
        settings.MODE = self.originals["MODE"]
        settings.SYMBOLS = self.originals["SYMBOLS"]
        settings.ALLOWED_SYMBOLS = self.originals["ALLOWED_SYMBOLS"]
        main.PROJECT_ROOT = self.originals["PROJECT_ROOT"]
        main.APP_PATH = self.originals["APP_PATH"]
        self.tmp.cleanup()

    def test_prune_stale_when_exchange_flat(self) -> None:
        main._save_positions(
            [
                ManagedPosition(
                    symbol="TAOUSDT",
                    direction="LONG",
                    qty_total=1.0,
                    qty_open=1.0,
                    entry=250.0,
                    stop_loss=248.0,
                    tp1=252.0,
                    tp2=254.0,
                    tp3=256.0,
                    open_time_iso=datetime.now(timezone.utc).isoformat(),
                )
            ],
            merge_disk_open=False,
        )
        stats = main.reconcile_all(
            SimpleNamespace(_client=_Client({"TAOUSDT": {"position_amt": 0.0, "entry_price": 0.0}}))
        )
        assert int(stats["pruned"]) == 1
        assert bool(stats["changed"])
        assert main._load_positions() == []

    def test_recreate_missing_when_exchange_has_open(self) -> None:
        stats = main.reconcile_all(
            SimpleNamespace(_client=_Client({"TAOUSDT": {"position_amt": 1.25, "entry_price": 275.5}}))
        )
        assert int(stats["created"]) == 1
        assert bool(stats["changed"])
        positions = main._load_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "TAOUSDT"
        assert positions[0].direction == "LONG"
        assert float(positions[0].qty_open) == pytest.approx(1.25, abs=1e-8)

    def test_dedupe_duplicate_open_rows_per_symbol(self) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        path = self.tmp_path / "runtime_data" / "runtime_positions.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                [
                    {
                        "symbol": "TAOUSDT",
                        "side": "BUY",
                        "status": "OPEN",
                        "position": {"qty_total": 1.0, "qty_open": 1.0, "entry_price": 250.0, "realized_pnl": 0.0},
                        "stop_loss": {"initial_stop_loss": 248.0, "current_stop_loss": 248.0, "initial_risk_usd": 2.0},
                        "take_profits": [
                            {"price": 252.0, "close_frac": 0.5, "tp1_hit": False},
                            {"price": 254.0, "close_frac": 0.3, "tp2_hit": False},
                            {"price": 256.0, "close_frac": 0.2, "tp3_hit": False},
                        ],
                        "exchange": {"stop_order_id": None, "last_sent_stop_loss": 0.0, "last_sent_qty": 0.0},
                        "meta": {"setup_type": "auto", "setup_grade": "A+"},
                        "timestamps": {"opened_at": now_iso},
                        "exit_tracking": {"max_roi_seen": 0.0},
                    },
                    {
                        "symbol": "TAOUSDT",
                        "side": "BUY",
                        "status": "OPEN",
                        "position": {"qty_total": 0.8, "qty_open": 0.8, "entry_price": 251.0, "realized_pnl": 0.0},
                        "stop_loss": {"initial_stop_loss": 248.5, "current_stop_loss": 248.5, "initial_risk_usd": 1.6},
                        "take_profits": [
                            {"price": 253.0, "close_frac": 0.5, "tp1_hit": False},
                            {"price": 255.0, "close_frac": 0.3, "tp2_hit": False},
                            {"price": 257.0, "close_frac": 0.2, "tp3_hit": False},
                        ],
                        "exchange": {"stop_order_id": None, "last_sent_stop_loss": 0.0, "last_sent_qty": 0.0},
                        "meta": {"setup_type": "manual", "setup_grade": "A"},
                        "timestamps": {"opened_at": now_iso},
                        "exit_tracking": {"max_roi_seen": 0.0},
                    },
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        stats = main.reconcile_all(
            SimpleNamespace(_client=_Client({"TAOUSDT": {"position_amt": 1.0, "entry_price": 250.0}}))
        )
        assert int(stats["pruned"]) == 1
        assert bool(stats["changed"])
        positions = main._load_positions()
        assert len(positions) == 1
        assert positions[0].symbol == "TAOUSDT"

    def test_fet_prunes_duplicate_trend_legs_to_single_book(self) -> None:
        settings.SYMBOLS = ["FETUSDT"]
        settings.ALLOWED_SYMBOLS = ["FETUSDT"]
        now_iso = datetime.now(timezone.utc).isoformat()
        main._save_positions(
            [
                ManagedPosition(
                    symbol="FETUSDT",
                    direction="LONG",
                    qty_total=10.0,
                    qty_open=10.0,
                    entry=0.2700,
                    stop_loss=0.2600,
                    tp1=0.2760,
                    tp2=0.2800,
                    tp3=0.2850,
                    setup_type="breakout",
                    strategy_family="trend",
                    open_time_iso=now_iso,
                ),
                ManagedPosition(
                    symbol="FETUSDT",
                    direction="LONG",
                    qty_total=9.0,
                    qty_open=9.0,
                    entry=0.2720,
                    stop_loss=0.2620,
                    tp1=0.2780,
                    tp2=0.2820,
                    tp3=0.2860,
                    setup_type="pullback",
                    strategy_family="trend",
                    open_time_iso=now_iso,
                ),
            ],
            merge_disk_open=False,
        )
        stats = main.reconcile_all(
            SimpleNamespace(_client=_Client({"FETUSDT": {"position_amt": 19.0, "entry_price": 0.2710}}))
        )
        assert int(stats["pruned"]) == 1
        assert bool(stats["changed"]) is True
        positions = main._load_positions()
        assert len(positions) == 1
        assert positions[0].setup_type == "breakout"
