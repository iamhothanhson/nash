from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.config import settings
from app.monitoring.events import emit_mode_event
from app.monitoring.logger import log
from app.monitoring.position_journal import log_position_closed, log_position_open
import app.monitoring.position_journal as position_journal


class TestFullLifecyclePositionLoggingRegression:
    def setup_method(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.old_cwd = Path.cwd()
        self.old_mode = settings.MODE
        self.old_repo_root = position_journal._repo_root
        settings.MODE = "demo"
        position_journal._repo_root = lambda: self.tmp_path
        os.chdir(self.tmp_path)

    def teardown_method(self) -> None:
        os.chdir(self.old_cwd)
        settings.MODE = self.old_mode
        position_journal._repo_root = self.old_repo_root
        self.tmp.cleanup()

    def _read_daily_log_lines(self) -> list[str]:
        path = self.tmp_path / "logs" / f"{datetime.now().strftime('%d-%b-%Y')}.log"
        if not path.exists():
            return []
        return [line.rstrip("\n") for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    @staticmethod
    def _without_time_prefix(line: str) -> str:
        # daily log format: [HH:MM:SS] message
        return line.split("] ", 1)[1] if "] " in line else line

    def _read_positions_history_journal(self, month: str) -> list[dict]:
        segs = month.split("-")
        assert len(segs) == 2
        yyyy, mm = segs[0], segs[1]
        path = self.tmp_path / "position_history" / f"{mm}-{yyyy}-positions-history.json"
        if not path.exists():
            return []
        return json.loads(path.read_text(encoding="utf-8"))

    def test_full_lifecycle_daily_log_line_by_line(self) -> None:
        log("[SIGNAL] TAOUSDT | LONG | entry=250.10")
        log("[PLAN] TAOUSDT | qty=1.3200 | risk=1.90 | SL=248.66")
        log("[RISK FLOW] TAOUSDT | Base=0.0240 | Signal=0.0240 | Planned=0.0240 | Final=0.0240")

        emit_mode_event(
            "demo",
            "TAOUSDT",
            "LONG",
            "OPEN",
            (
                "Strategy: Liquidity | Setup: Liquidity Sweep Reversal | Entry: 250.10 | "
                "Size: 330.13 USDT | Margin: 47.16 | "
                "SL: 248.66 (-0.58%) | TP1: 252.60 (1.00%) | TP2: 255.10 (2.00%) | "
                "TP3: 257.60 (3.00%) | Risk: 1.90 USDT"
            ),
        )
        emit_mode_event(
            "demo",
            "TAOUSDT",
            "LONG",
            "TP1 HIT",
            "Price: 252.60 | Closed: 165.07 USDT | Remaining: 165.07 USDT | PNL: +1.65 USDT",
        )
        emit_mode_event(
            "demo",
            "TAOUSDT",
            "LONG",
            "BREAKEVEN",
            "SL → Entry (250.10) | Remaining: 165.07 USDT | Risk: 0 USDT",
        )
        emit_mode_event(
            "demo",
            "TAOUSDT",
            "LONG",
            "TP2 HIT",
            "Price: 255.10 | Closed: 99.04 USDT | Remaining: 66.03 USDT | PNL: +1.98 USDT",
        )
        emit_mode_event(
            "demo",
            "TAOUSDT",
            "LONG",
            "TP3 HIT",
            "Price: 257.60 | Closed: 66.03 USDT | Remaining: 0.00 USDT | PNL: +1.98 USDT",
        )
        emit_mode_event(
            "demo",
            "TAOUSDT",
            "LONG",
            "CLOSE",
            (
                "Size: 330.13 USDT | Margin: 47.16 USDT | Entry: 250.10 | "
                "Exit: 257.60 | Duration: 20.7 min | Total PNL: +5.61 USDT"
            ),
        )
        # Also validate open/close journal logging entries are written.
        t_open = datetime(2026, 4, 27, 9, 0, 2, tzinfo=timezone.utc).isoformat()
        t_close = datetime(2026, 4, 27, 9, 20, 44, tzinfo=timezone.utc).isoformat()
        log_position_open(
            time_iso=t_open,
            symbol="TAOUSDT",
            direction="LONG",
            entry=250.1,
            stop_loss=248.66,
            tp1=252.601,
            tp2=255.102,
            tp3=257.603,
            size_usdt=330.13,
            leverage=7,
            risk_usdt=1.90,
            partial_close=[0.5, 0.3, 0.2],
        )
        month = "2026-04"
        after_open = self._read_positions_history_journal(month)
        assert len(after_open) == 1
        assert after_open[0]["status"] == "Open"
        tp_open = after_open[0]["take_profit"]
        assert tp_open[0]["tp1_hit"] is False and "tp2_hit" not in tp_open[0] and "tp3_hit" not in tp_open[0]
        assert tp_open[1]["tp2_hit"] is False and "tp1_hit" not in tp_open[1] and "tp3_hit" not in tp_open[1]
        assert tp_open[2]["tp3_hit"] is False and "tp1_hit" not in tp_open[2] and "tp2_hit" not in tp_open[2]
        assert after_open[0]["closed_reason"] is None
        assert after_open[0]["strategy_setup"] == "liquidity_sweep_reversal"
        ko = list(after_open[0].keys())
        assert ko.index("strategy_setup") == ko.index("side") + 1
        log_position_closed(
            time_iso=t_close,
            symbol="TAOUSDT",
            direction="LONG",
            open_time_iso=t_open,
            entry=250.1,
            stop_loss=248.66,
            tp1=252.601,
            tp2=255.102,
            tp3=257.603,
            qty_total=1.32,
            leverage=7,
            risk_usdt=1.90,
            pnl_usdt=5.61,
            balance_usdt=338.61,
            tp1_hit=True,
            tp2_hit=True,
            tp3_hit=True,
            closed_reason="TP3 HIT",
        )

        expected = [
            "[SIGNAL] TAOUSDT | LONG | entry=250.10",
            "[PLAN] TAOUSDT | qty=1.3200 | risk=1.90 | SL=248.66",
            "[RISK FLOW] TAOUSDT | Base=0.0240 | Signal=0.0240 | Planned=0.0240 | Final=0.0240",
            "[DEMO] [OPEN] TAOUSDT [LONG] | Strategy: Liquidity | Setup: Liquidity Sweep Reversal | Entry: 250.10 | Size: 330.13 USDT | Margin: 47.16 | SL: 248.66 (-0.58%) | TP1: 252.60 (1.00%) | TP2: 255.10 (2.00%) | TP3: 257.60 (3.00%) | Risk: 1.90 USDT",
            "[DEMO] [TP1 HIT] TAOUSDT [LONG] | Price: 252.60 | Closed: 165.07 USDT | Remaining: 165.07 USDT | PNL: +1.65 USDT",
            "[DEMO] [BREAKEVEN] TAOUSDT [LONG] | SL → Entry (250.10) | Remaining: 165.07 USDT | Risk: 0 USDT",
            "[DEMO] [TP2 HIT] TAOUSDT [LONG] | Price: 255.10 | Closed: 99.04 USDT | Remaining: 66.03 USDT | PNL: +1.98 USDT",
            "[DEMO] [TP3 HIT] TAOUSDT [LONG] | Price: 257.60 | Closed: 66.03 USDT | Remaining: 0.00 USDT | PNL: +1.98 USDT",
            "[DEMO] [CLOSE] TAOUSDT [LONG] | Size: 330.13 USDT | Margin: 47.16 USDT | Entry: 250.10 | Exit: 257.60 | Duration: 20.7 min | Total PNL: +5.61 USDT",
        ]

        got = [self._without_time_prefix(line) for line in self._read_daily_log_lines()]
        assert got == expected
        opened = self._read_positions_history_journal(month)
        assert len(opened) == 1
        assert opened[0]["status"] == "Closed"
        assert opened[0]["opened"] == "Apr-27-2026 09:00:02"
        assert opened[0]["closed"] == "Apr-27-2026 09:20:44"
        assert opened[0]["symbol"] == "TAOUSDT"
        assert float(opened[0]["pnl_usdt"]) == pytest.approx(5.61, abs=1e-2)
        assert float(opened[0]["balance_usdt"]) == pytest.approx(338.61, abs=1e-2)
        assert not (self.tmp_path / "position_history" / f"closed-positions-{month}.json").exists()
        tp = opened[0]["take_profit"]
        assert tp[0]["tp1_hit"] is True and "tp2_hit" not in tp[0] and "tp3_hit" not in tp[0]
        assert tp[1]["tp2_hit"] is True and "tp1_hit" not in tp[1] and "tp3_hit" not in tp[1]
        assert tp[2]["tp3_hit"] is True and "tp1_hit" not in tp[2] and "tp2_hit" not in tp[2]
        keys = list(opened[0].keys())
        assert keys.index("closed_reason") == keys.index("balance_usdt") + 1
        assert opened[0]["closed_reason"] == "TP3 HIT"
        assert opened[0]["strategy_setup"] == "liquidity_sweep_reversal"
