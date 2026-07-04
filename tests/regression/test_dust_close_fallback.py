from __future__ import annotations

import sys
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

import main
from app.config import settings


class _Client:
    def __init__(self, amt: float, raise_error: bool = False):
        self._amt = amt
        self._raise_error = raise_error

    def get_position_amount(self, symbol: str) -> float:
        if self._raise_error:
            raise RuntimeError("exchange unavailable")
        return self._amt


class _Engine:
    def __init__(self, client):
        self._client = client


class TestDustCloseFallbackRegression:
    def setup_method(self) -> None:
        self.orig_enabled = settings.POSITION_DUST_CLOSE_ENABLED
        self.orig_threshold = settings.POSITION_DUST_CLOSE_NOTIONAL_USDT
        settings.POSITION_DUST_CLOSE_ENABLED = True
        settings.POSITION_DUST_CLOSE_NOTIONAL_USDT = 7.0

    def teardown_method(self) -> None:
        settings.POSITION_DUST_CLOSE_ENABLED = self.orig_enabled
        settings.POSITION_DUST_CLOSE_NOTIONAL_USDT = self.orig_threshold

    def test_detects_dust_remainder_under_threshold(self) -> None:
        is_dust, amt, notional = main._is_exchange_dust_remainder(
            engine=_Engine(_Client(amt=0.01)),
            symbol="TAOUSDT",
            mark_price=100.0,
        )
        assert is_dust
        assert amt == pytest.approx(0.01, abs=1e-8)
        assert notional == pytest.approx(1.0, abs=1e-8)

    def test_not_dust_when_over_threshold(self) -> None:
        is_dust, amt, notional = main._is_exchange_dust_remainder(
            engine=_Engine(_Client(amt=0.2)),
            symbol="TAOUSDT",
            mark_price=100.0,
        )
        assert not is_dust
        assert amt == pytest.approx(0.2, abs=1e-8)
        assert notional == pytest.approx(20.0, abs=1e-8)

    def test_fallback_on_exchange_error(self) -> None:
        is_dust, amt, notional = main._is_exchange_dust_remainder(
            engine=_Engine(_Client(amt=0.0, raise_error=True)),
            symbol="TAOUSDT",
            mark_price=100.0,
        )
        assert not is_dust
        assert amt == 0.0
        assert notional == 0.0
