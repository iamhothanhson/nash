from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

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
    def get_position_risk_snapshot(self, symbol: str) -> dict[str, float]:
        return {"position_amt": 2.0, "entry_price": 300.0}


class TestManualOpenMergePersistenceRegression:
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

    def test_manual_open_survives_save_load_reconcile_without_duplicates(self) -> None:
        runtime_path = self.tmp_path / "runtime_data" / "runtime_positions.json"
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        opened_at = datetime.now(timezone.utc).isoformat()
        manual_row = {
            "symbol": "TAOUSDT",
            "side": "BUY",
            "status": "OPEN",
            "position": {"qty_total": 2.0, "qty_open": 2.0, "entry_price": 300.0, "realized_pnl": 0.0},
            "stop_loss": {"initial_stop_loss": 295.0, "current_stop_loss": 295.0, "initial_risk_usd": 10.0},
            "take_profits": [
                {"price": 305.0, "close_frac": 0.5, "tp1_hit": False},
                {"price": 310.0, "close_frac": 0.3, "tp2_hit": False},
                {"price": 315.0, "close_frac": 0.2, "tp3_hit": False},
            ],
            "exchange": {"stop_order_id": None, "last_sent_stop_loss": 0.0, "last_sent_qty": 0.0},
            "meta": {"setup_type": "manual", "setup_grade": "A+"},
            "timestamps": {"opened_at": opened_at},
            "exit_tracking": {"max_roi_seen": 0.0},
        }
        runtime_path.write_text(json.dumps([manual_row], indent=2), encoding="utf-8")

        # Simulate loop save pass while memory list is currently empty.
        main._save_positions([], merge_disk_open=True)
        after_save = json.loads(runtime_path.read_text(encoding="utf-8"))
        assert len(after_save) == 1
        assert after_save[0]["symbol"] == "TAOUSDT"

        # Merge from disk into in-memory loop state and ensure no duplication.
        positions: list[ManagedPosition] = []
        per_symbol = {"TAOUSDT": 0}
        main._merge_positions_from_disk(positions, per_symbol)
        assert len(positions) == 1
        assert per_symbol["TAOUSDT"] == 1
        main._merge_positions_from_disk(positions, per_symbol)
        assert len(positions) == 1
        assert per_symbol["TAOUSDT"] == 1

        # Save in-memory state and reconcile with exchange snapshot.
        main._save_positions(positions, merge_disk_open=True)
        stats = main.reconcile_all(SimpleNamespace(_client=_Client()))
        assert "changed" in stats
        final_rows = json.loads(runtime_path.read_text(encoding="utf-8"))
        open_rows = [
            r
            for r in final_rows
            if str(r.get("symbol", "")).strip().upper() == "TAOUSDT"
            and str(r.get("status", "")).strip().upper() == "OPEN"
            and float((r.get("position") or {}).get("qty_open", 0.0)) > 0.0
        ]
        assert len(open_rows) == 1
