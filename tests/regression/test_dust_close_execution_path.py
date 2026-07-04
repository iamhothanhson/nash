from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import main
from app.config import settings
from app.order_planning.order_planner import DailyState
from app.portfolio.capital_tracker import VirtualAccount
from app.position_management.staged import ExitFill, ManagedPosition


class _Engine:
    def __init__(self) -> None:
        self.close_order_calls: list[tuple[str, str, float]] = []

    def close_order(self, symbol: str, side: str, qty: float):
        self.close_order_calls.append((symbol, side, float(qty)))
        # Force dust fallback branch.
        return None


class TestDustCloseExecutionPathRegression:
    def setup_method(self) -> None:
        self.orig_mode = settings.MODE
        self.orig_symbols = settings.SYMBOLS
        self.orig_allowed = settings.ALLOWED_SYMBOLS
        self.orig_dust_enabled = settings.POSITION_DUST_CLOSE_ENABLED
        settings.MODE = "live"
        settings.SYMBOLS = ["TAOUSDT"]
        settings.ALLOWED_SYMBOLS = ["TAOUSDT"]
        settings.POSITION_DUST_CLOSE_ENABLED = True

    def teardown_method(self) -> None:
        settings.MODE = self.orig_mode
        settings.SYMBOLS = self.orig_symbols
        settings.ALLOWED_SYMBOLS = self.orig_allowed
        settings.POSITION_DUST_CLOSE_ENABLED = self.orig_dust_enabled

    @staticmethod
    def _df() -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 10.0},
                {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 11.0},
            ]
        )

    @staticmethod
    def _closing_fills(pos: ManagedPosition) -> list[ExitFill]:
        pos.qty_open = 0.0
        pos.closed = True
        return [
            ExitFill("TP3 HIT", 100.0, 1.0, 0.0, 1.0),
            ExitFill("CLOSE", 100.0, 0.0, 0.0, 1.0),
        ]

    def _run_manage_once(self, *, dust_close_success: bool) -> ManagedPosition:
        engine = _Engine()
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
        )
        positions = [pos]
        state = DailyState()
        virtual = VirtualAccount(1000.0)

        with patch("main._fetch_klines", return_value=self._df()), patch(
            "main.apply_staged_management",
            side_effect=lambda *args, **kwargs: self._closing_fills(pos),
        ), patch("main._is_exchange_dust_remainder", return_value=(True, 0.01, 1.0)), patch(
            "main._attempt_exchange_dust_close", return_value=dust_close_success
        ) as mock_dust_close, patch("main.emit_mode_event"), patch("main.log_position_closed"):
            main._manage_open_positions(
                engine=engine,
                virtual=virtual,
                state=state,
                positions=positions,
                positions_per_symbol={"TAOUSDT": 1},
                performance_history={},
                total_closed_pnl=0.0,
                hard_stop_reentry_until={},
            )

        assert len(engine.close_order_calls) == 1
        mock_dust_close.assert_called_once()
        return pos

    def test_dust_fallback_attempt_invoked(self) -> None:
        pos = self._run_manage_once(dust_close_success=True)
        assert pos.closed

    def test_close_state_reopens_when_dust_sync_fails(self) -> None:
        pos = self._run_manage_once(dust_close_success=False)
        assert not pos.closed
