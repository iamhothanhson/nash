from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

_PROJECT = Path(__file__).resolve().parents[2]
_APP = _PROJECT / "app"
for _p in (_PROJECT, _APP):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import main
from app.config import settings
from app.order_planning.order_planner import DailyState
from app.portfolio.capital_tracker import VirtualAccount
from app.position_management.staged import ExitFill, ManagedPosition


def _mock_klines() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=10, freq="5min", tz="UTC"),
            "open": [100.0] * 10,
            "high": [100.2] * 10,
            "low": [99.8] * 10,
            "close": [100.0] * 10,
            "volume": [1000.0] * 10,
        }
    )


def test_live_sl_close_sets_symbol_reentry_cooldown() -> None:
    originals = {
        "MODE": settings.MODE,
        "SL_REENTRY_COOLDOWN_SEC": getattr(settings, "SL_REENTRY_COOLDOWN_SEC", 120.0),
        "HARD_STOP_REENTRY_COOLDOWN_SEC": settings.HARD_STOP_REENTRY_COOLDOWN_SEC,
    }
    settings.MODE = "live"
    settings.SL_REENTRY_COOLDOWN_SEC = 90.0
    settings.HARD_STOP_REENTRY_COOLDOWN_SEC = 120.0

    try:
        pos = ManagedPosition(
            symbol="TAOUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=1.0,
            entry=100.0,
            stop_loss=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=103.0,
            open_time_iso="2026-01-01T00:00:00+00:00",
            initial_risk_usd=1.0,
        )
        positions = [pos]
        positions_per_symbol = {"TAOUSDT": 1}
        cooldowns: dict[str, float] = {}
        engine = SimpleNamespace(
            close_order=lambda *args, **kwargs: {"status": "ok"},
            sync_stop_loss=lambda *args, **kwargs: None,
        )
        virtual = VirtualAccount(1000.0)
        state = DailyState()
        now = time.time()

        bar_slice = SimpleNamespace(
            bar_ts=now,
            high=100.2,
            low=98.8,
            close_px=99.0,
            candles_5m=[{"open": 100.0, "high": 100.2, "low": 98.8, "close": 99.0}],
            candles_15m=[],
        )

        def _staged_sl_close(position, **kwargs):
            position.qty_open = 0.0
            position.closed = True
            position.realized_pnl = -1.0
            return [
                ExitFill("SL HIT", 99.0, 1.0, 0.0, -1.0),
                ExitFill("CLOSE", 99.0, 1.0, 0.0, -1.0),
            ]

        with patch("main._fetch_klines", return_value=_mock_klines()), patch(
            "main.build_exit_bar_slice", return_value=bar_slice
        ), patch(
            "main.apply_staged_management",
            side_effect=_staged_sl_close,
        ), patch(
            "main._is_exchange_dust_remainder", return_value=(False, 0.0, 0.0)
        ), patch("main.risk_limit_tracking.record_full_position_close"), patch(
            "main._save_positions"
        ), patch("main.log_position_closed"), patch(
            "main.emit_mode_event"
        ), patch("main._cli_print"), patch(
            "main.get_runtime_account_state",
            return_value={
                "risk_balance": 1000.0,
                "available_balance": 800.0,
                "open_notional": 0.0,
            },
        ):
            _ = main._manage_open_positions(
                engine=engine,
                virtual=virtual,
                state=state,
                positions=positions,
                positions_per_symbol=positions_per_symbol,
                performance_history={"TAOUSDT": []},
                total_closed_pnl=0.0,
                hard_stop_reentry_until=cooldowns,
            )

        assert not positions
        assert positions_per_symbol["TAOUSDT"] == 0
        assert cooldowns["TAOUSDT"] >= now + 89.0
    finally:
        settings.MODE = originals["MODE"]
        settings.SL_REENTRY_COOLDOWN_SEC = originals["SL_REENTRY_COOLDOWN_SEC"]
        settings.HARD_STOP_REENTRY_COOLDOWN_SEC = originals["HARD_STOP_REENTRY_COOLDOWN_SEC"]
