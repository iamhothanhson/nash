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


class _FlatClient:
    def get_position_risk_snapshot(self, symbol: str) -> dict[str, float]:
        return {"position_amt": 0.0, "entry_price": 0.0}

    def get_user_trades(self, symbol: str, **kwargs) -> list[dict]:
        return []

    def get_all_algo_orders(self, symbol: str, **kwargs) -> list[dict]:
        return []


class TestRuntimePositionsRoundtripIntegration:
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

    def test_save_load_merge_and_reconcile_roundtrip(self) -> None:
        pos = ManagedPosition(
            symbol="TAOUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=1.0,
            entry=250.1,
            stop_loss=248.7,
            tp1=252.6,
            tp2=255.1,
            tp3=257.6,
            open_time_iso=datetime.now(timezone.utc).isoformat(),
            initial_risk_usd=1.9,
        )
        main._save_positions([pos], merge_disk_open=False)

        loaded = main._load_positions()
        assert len(loaded) == 1
        assert loaded[0].symbol == "TAOUSDT"
        assert loaded[0].qty_open > 0.0

        positions: list[ManagedPosition] = []
        per_symbol = {"TAOUSDT": 0}
        main._merge_positions_from_disk(positions, per_symbol)
        assert len(positions) == 1
        assert per_symbol["TAOUSDT"] == 1

        stats = main.reconcile_all(SimpleNamespace(_client=_FlatClient()))
        assert int(stats["pruned"]) == 1
        assert bool(stats["changed"])

        runtime_path = self.tmp_path / "runtime_data" / "runtime_positions.json"
        assert json.loads(runtime_path.read_text(encoding="utf-8")) == []

    def test_save_load_preserves_render_tp_decimal_precision(self) -> None:
        pos = ManagedPosition(
            symbol="RENDERUSDT",
            direction="LONG",
            qty_total=15.0,
            qty_open=15.0,
            entry=2.011,
            stop_loss=1.988,
            tp1=2.020,
            tp2=2.040,
            tp3=2.050,
            open_time_iso=datetime.now(timezone.utc).isoformat(),
            initial_risk_usd=0.29,
        )
        main._save_positions([pos], merge_disk_open=False)

        loaded = main._load_positions()
        assert len(loaded) == 1
        assert loaded[0].tp2 == 2.040

        runtime_path = self.tmp_path / "runtime_data" / "runtime_positions.json"
        rows = json.loads(runtime_path.read_text(encoding="utf-8"))
        assert rows[0]["take_profits"][1]["price"] == 2.040
