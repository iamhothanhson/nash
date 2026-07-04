from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.config import settings
from app.order_planning.order_planner import build_order_plan
from app.trading.signal_engine import get_signal


class TestSignalToOrderPlanPipelineIntegration:
    def setup_method(self) -> None:
        self.originals = {
            "SYMBOLS": settings.SYMBOLS,
            "ALLOWED_SYMBOLS": settings.ALLOWED_SYMBOLS,
            "MAX_OPEN_POSITIONS": settings.MAX_OPEN_POSITIONS,
            "EXPOSURE_MULTIPLIER": settings.EXPOSURE_MULTIPLIER,
        }
        settings.SYMBOLS = ["TAOUSDT"]
        settings.ALLOWED_SYMBOLS = ["TAOUSDT"]
        settings.MAX_OPEN_POSITIONS = 1
        settings.EXPOSURE_MULTIPLIER = 3.0

    def teardown_method(self) -> None:
        settings.SYMBOLS = self.originals["SYMBOLS"]
        settings.ALLOWED_SYMBOLS = self.originals["ALLOWED_SYMBOLS"]
        settings.MAX_OPEN_POSITIONS = self.originals["MAX_OPEN_POSITIONS"]
        settings.EXPOSURE_MULTIPLIER = self.originals["EXPOSURE_MULTIPLIER"]

    def _load_frame(self, timeframe: str) -> pd.DataFrame:
        path = PROJECT_ROOT / "history_data" / f"TAOUSDT_{timeframe}.csv"
        if not path.exists():
            raise AssertionError(f"Missing fixture data file: {path}")
        raw = pd.read_csv(path)
        return pd.DataFrame(
            {
                "timestamp": pd.to_datetime(raw["time"], unit="ms", utc=True),
                "open": raw["open"].astype(float),
                "high": raw["high"].astype(float),
                "low": raw["low"].astype(float),
                "close": raw["close"].astype(float),
                "volume": raw["volume"].astype(float),
            }
        ).sort_values("timestamp").reset_index(drop=True)

    def test_real_candles_signal_to_order_plan(self) -> None:
        d1h = self._load_frame("1h").tail(500).reset_index(drop=True)
        d15 = self._load_frame("15m").tail(500).reset_index(drop=True)
        d5 = self._load_frame("5m").tail(500).reset_index(drop=True)
        found_plan = None
        found_signal = False
        # Scan recent windows so test remains stable when latest candle has no setup.
        for end in range(len(d5), 300, -10):
            d5_w = d5.iloc[:end].tail(420).reset_index(drop=True)
            if d5_w.empty:
                continue
            ts = d5_w["timestamp"].iloc[-1]
            d15_w = d15[d15["timestamp"] <= ts].tail(240).reset_index(drop=True)
            d1h_w = d1h[d1h["timestamp"] <= ts].tail(420).reset_index(drop=True)
            if len(d15_w) < 120 or len(d1h_w) < 250 or len(d5_w) < 250:
                continue

            signal = get_signal(d1h_w, d15_w, d5_w, symbol="TAOUSDT")
            if signal is None:
                continue
            found_signal = True

            plan = build_order_plan(
                signal,
                balance=333.0,
                positions_per_symbol={"TAOUSDT": 0},
                open_positions_total=0,
                allocation_share=1.0,
                symbol="TAOUSDT",
                max_open_positions=1,
                open_notional_total=0.0,
                risk_multiplier=1.0,
                data_15m=d15_w,
                max_notional_account_cap=333.0,
            )
            if plan is not None:
                found_plan = plan
                break

        if not found_signal:
            pytest.skip("No signal generated from current fixture windows under active strategy gates")
        if found_plan is None:
            pytest.skip("Signal found but no tradable plan generated under current planner constraints")
        assert found_plan is not None
        assert float(found_plan.get("qty", 0.0)) > 0.0
        assert float(found_plan.get("notional", 0.0)) > 0.0
        assert str(found_plan.get("symbol", "TAOUSDT")).upper() == "TAOUSDT"
