from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import main

settings = main.settings
from app.order_planning.order_planner import DailyState
from app.portfolio.capital_tracker import VirtualAccount


class TestRunCycleWithMockedPlanIntegration:
    def setup_method(self) -> None:
        self.originals = {
            "MODE": settings.MODE,
            "AI_ENABLED": settings.AI_ENABLED,
            "MAX_OPEN_POSITIONS": settings.MAX_OPEN_POSITIONS,
            "LEVERAGE": settings.LEVERAGE,
            "SYMBOLS": settings.SYMBOLS,
            "ALLOWED_SYMBOLS": settings.ALLOWED_SYMBOLS,
        }
        settings.MODE = "backtest"
        settings.AI_ENABLED = False
        settings.MAX_OPEN_POSITIONS = 1
        settings.LEVERAGE = 7
        settings.SYMBOLS = ["TAOUSDT"]
        settings.ALLOWED_SYMBOLS = ["TAOUSDT"]

    def teardown_method(self) -> None:
        settings.MODE = self.originals["MODE"]
        settings.AI_ENABLED = self.originals["AI_ENABLED"]
        settings.MAX_OPEN_POSITIONS = self.originals["MAX_OPEN_POSITIONS"]
        settings.LEVERAGE = self.originals["LEVERAGE"]
        settings.SYMBOLS = self.originals["SYMBOLS"]
        settings.ALLOWED_SYMBOLS = self.originals["ALLOWED_SYMBOLS"]

    def _frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "timestamp": pd.date_range("2026-01-01", periods=300, freq="h", tz="UTC"),
                "open": [100.0] * 300,
                "high": [101.0] * 300,
                "low": [99.0] * 300,
                "close": [100.5] * 300,
                "volume": [1000.0] * 300,
            }
        )

    def test_run_cycle_open_path_with_mocked_plan(self) -> None:
        d1h = self._frame()
        d15 = self._frame()
        d5 = self._frame()
        virtual = VirtualAccount(333.0)
        state = DailyState()
        engine = SimpleNamespace(
            place_order=lambda *args, **kwargs: {"stop_exchange_order_id": 1234},
            last_place_order_failure=None,
        )
        signal = {"direction": "LONG", "entry": 100.5, "setup_score": 9, "setup_grade": "A"}
        plan = {
            "direction": "LONG",
            "entry": 100.5,
            "stop_loss": 99.5,
            "tp1": 101.5,
            "tp2": 102.5,
            "tp3": 103.5,
            "qty": 0.5,
            "notional": 50.25,
            "risk_percent": 0.02,
            "setup_type": "liquidity",
            "setup_grade": "A",
            "partial_close": [0.5, 0.3, 0.2],
            "setup_score": 9,
            "confirmation_mode": "normal",
        }

        with patch("main.risk_controls_allow", return_value=True), patch(
            "main.risk_limit_tracking.risk_file_entry_gate", return_value=(True, None)
        ), patch("main.risk_limit_tracking.record_new_open"), patch(
            "main._exchange_symbol_has_open_position", return_value=False
        ), patch("main.compute_risk_multiplier", return_value=(1.0, None)), patch(
            "main.build_order_plan", return_value=plan
        ), patch("main.passes_coin_execution_gates", return_value=True), patch(
            "main.log_position_open"
        ), patch(
            "main.emit_mode_event"
        ):
            pos = main.run_cycle(
                d1h,
                d15,
                d5,
                virtual=virtual,
                state=state,
                symbol="TAOUSDT",
                positions_per_symbol={"TAOUSDT": 0},
                open_positions_total=0,
                engine=engine,
                allocation_share=1.0,
                signal=signal,
            )

        assert pos is not None
        assert pos.symbol == "TAOUSDT"
        assert pos.direction == "LONG"
        assert pos.qty_open > 0.0

    def test_run_cycle_live_uses_leveraged_available_balance_as_account_cap(self) -> None:
        d1h = self._frame()
        d15 = self._frame()
        d5 = self._frame()
        virtual = VirtualAccount(333.0)
        state = DailyState()
        engine = SimpleNamespace(
            place_order=lambda *args, **kwargs: {"stop_exchange_order_id": 1234},
            last_place_order_failure=None,
        )
        signal = {"direction": "LONG", "entry": 100.5, "setup_score": 9, "setup_grade": "A"}
        plan = {
            "direction": "LONG",
            "entry": 100.5,
            "stop_loss": 99.5,
            "tp1": 101.5,
            "tp2": 102.5,
            "tp3": 103.5,
            "qty": 0.5,
            "notional": 50.25,
            "risk_percent": 0.02,
            "setup_type": "liquidity",
            "setup_grade": "A",
            "partial_close": [0.5, 0.3, 0.2],
            "setup_score": 9,
            "confirmation_mode": "normal",
        }
        settings.MODE = "live"
        settings.LEVERAGE = 5
        available_balance = 67.04
        expected_cap = available_balance * settings.LEVERAGE

        with patch("main.risk_controls_allow", return_value=True), patch(
            "main.risk_limit_tracking.risk_file_entry_gate", return_value=(True, None)
        ), patch("main.risk_limit_tracking.record_new_open"), patch(
            "main._exchange_symbol_has_open_position", return_value=False
        ), patch("main.compute_risk_multiplier", return_value=(1.0, None)), patch(
            "main.build_order_plan", return_value=plan
        ) as build_plan_mock, patch("main.passes_coin_execution_gates", return_value=True), patch(
            "main.log_position_open"
        ), patch(
            "main.emit_mode_event"
        ):
            pos = main.run_cycle(
                d1h,
                d15,
                d5,
                virtual=virtual,
                state=state,
                symbol="TAOUSDT",
                positions_per_symbol={"TAOUSDT": 0},
                open_positions_total=0,
                engine=engine,
                allocation_share=1.0,
                signal=signal,
                account_balance=100.0,
                available_balance=available_balance,
            )

        assert pos is not None
        assert build_plan_mock.call_args is not None
        assert float(build_plan_mock.call_args.kwargs["max_notional_account_cap"]) == expected_cap

    def test_run_cycle_live_falls_back_to_risk_balance_when_available_balance_missing(self) -> None:
        d1h = self._frame()
        d15 = self._frame()
        d5 = self._frame()
        virtual = VirtualAccount(333.0)
        state = DailyState()
        engine = SimpleNamespace(
            place_order=lambda *args, **kwargs: {"stop_exchange_order_id": 1234},
            last_place_order_failure=None,
        )
        signal = {"direction": "LONG", "entry": 100.5, "setup_score": 9, "setup_grade": "A"}
        plan = {
            "direction": "LONG",
            "entry": 100.5,
            "stop_loss": 99.5,
            "tp1": 101.5,
            "tp2": 102.5,
            "tp3": 103.5,
            "qty": 0.5,
            "notional": 50.25,
            "risk_percent": 0.02,
            "setup_type": "liquidity",
            "setup_grade": "A",
            "partial_close": [0.5, 0.3, 0.2],
            "setup_score": 9,
            "confirmation_mode": "normal",
        }
        settings.MODE = "live"
        settings.LEVERAGE = 5
        risk_balance = 88.0
        expected_cap = risk_balance * settings.LEVERAGE

        with patch("main.risk_controls_allow", return_value=True), patch(
            "main.risk_limit_tracking.risk_file_entry_gate", return_value=(True, None)
        ), patch(
            "main._exchange_symbol_has_open_position", return_value=False
        ), patch("main.compute_risk_multiplier", return_value=(1.0, None)), patch(
            "main.build_order_plan", return_value=plan
        ) as build_plan_mock, patch("main.passes_coin_execution_gates", return_value=True), patch(
            "main.log_position_open"
        ), patch(
            "main.emit_mode_event"
        ):
            pos = main.run_cycle(
                d1h,
                d15,
                d5,
                virtual=virtual,
                state=state,
                symbol="TAOUSDT",
                positions_per_symbol={"TAOUSDT": 0},
                open_positions_total=0,
                engine=engine,
                allocation_share=1.0,
                signal=signal,
                account_balance=risk_balance,
                available_balance=None,
            )

        assert pos is not None
        assert build_plan_mock.call_args is not None
        kwargs = build_plan_mock.call_args.kwargs
        assert float(kwargs["max_notional_account_cap"]) == expected_cap
        assert float(kwargs["available_balance"]) == risk_balance

    def test_run_cycle_demo_uses_available_balance_like_live(self) -> None:
        d1h = self._frame()
        d15 = self._frame()
        d5 = self._frame()
        virtual = VirtualAccount(333.0)
        state = DailyState()
        engine = SimpleNamespace(
            place_order=lambda *args, **kwargs: {"stop_exchange_order_id": 1234},
            last_place_order_failure=None,
        )
        signal = {"direction": "LONG", "entry": 100.5, "setup_score": 9, "setup_grade": "A"}
        plan = {
            "direction": "LONG",
            "entry": 100.5,
            "stop_loss": 99.5,
            "tp1": 101.5,
            "tp2": 102.5,
            "tp3": 103.5,
            "qty": 0.5,
            "notional": 50.25,
            "risk_percent": 0.02,
            "setup_type": "liquidity",
            "setup_grade": "A",
            "partial_close": [0.5, 0.3, 0.2],
            "setup_score": 9,
            "confirmation_mode": "normal",
        }
        settings.MODE = "demo"
        settings.LEVERAGE = 5
        available_balance = 42.0
        risk_balance = 120.0
        expected_cap = available_balance * settings.LEVERAGE

        with patch("main.risk_controls_allow", return_value=True), patch(
            "main.risk_limit_tracking.risk_file_entry_gate", return_value=(True, None)
        ), patch("main.risk_limit_tracking.record_new_open"), patch(
            "main._exchange_symbol_has_open_position", return_value=False
        ), patch("main.compute_risk_multiplier", return_value=(1.0, None)), patch(
            "main.build_order_plan", return_value=plan
        ) as build_plan_mock, patch("main.passes_coin_execution_gates", return_value=True), patch(
            "main.log_position_open"
        ), patch(
            "main.emit_mode_event"
        ):
            pos = main.run_cycle(
                d1h,
                d15,
                d5,
                virtual=virtual,
                state=state,
                symbol="TAOUSDT",
                positions_per_symbol={"TAOUSDT": 0},
                open_positions_total=0,
                engine=engine,
                allocation_share=1.0,
                signal=signal,
                account_balance=risk_balance,
                available_balance=available_balance,
            )

        assert pos is not None
        assert build_plan_mock.call_args is not None
        kwargs = build_plan_mock.call_args.kwargs
        assert kwargs.get("virtual") is None
        assert float(kwargs["max_notional_account_cap"]) == expected_cap
        assert float(kwargs["available_balance"]) == available_balance
        assert float(kwargs["balance"]) == risk_balance

    def test_run_cycle_live_skips_when_symbol_in_reentry_cooldown(self) -> None:
        d1h = self._frame()
        d15 = self._frame()
        d5 = self._frame()
        virtual = VirtualAccount(333.0)
        state = DailyState()
        engine = SimpleNamespace(
            place_order=lambda *args, **kwargs: {"stop_exchange_order_id": 1234},
            last_place_order_failure=None,
        )
        signal = {"direction": "LONG", "entry": 100.5, "setup_score": 9, "setup_grade": "A"}
        settings.MODE = "live"

        with patch("main.risk_controls_allow", return_value=True), patch(
            "main.risk_limit_tracking.risk_file_entry_gate", return_value=(True, None)
        ), patch(
            "main._exchange_symbol_has_open_position", return_value=False
        ) as exchange_open_mock:
            pos = main.run_cycle(
                d1h,
                d15,
                d5,
                virtual=virtual,
                state=state,
                symbol="TAOUSDT",
                positions_per_symbol={"TAOUSDT": 0},
                open_positions_total=0,
                engine=engine,
                allocation_share=1.0,
                signal=signal,
                hard_stop_reentry_until={"TAOUSDT": time.time() + 60.0},
            )

        assert pos is None
        exchange_open_mock.assert_not_called()
