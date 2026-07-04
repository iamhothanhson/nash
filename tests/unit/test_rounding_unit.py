from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.common.rounding import format_price, round_price, round_qty, round_ratio, round_usd


class TestRoundingUnit:
    def test_round_price_uses_tick(self) -> None:
        assert round_price(10.126, 0.01) == 10.13
        assert round_price(10.126, 0.1) == 10.1

    def test_round_price_invalid_tick_falls_back(self) -> None:
        assert round_price(1.236, 0.0) == 1.24
        assert round_price(1.236, -1.0) == 1.24

    def test_format_price_respects_decimals(self) -> None:
        assert format_price(252.601, 2) == "252.60"
        assert format_price(1.2, 4) == "1.2000"
        assert format_price(10.0, 0) == "10"

    def test_round_qty_usd_ratio(self) -> None:
        assert round_qty(1.23456, 3) == 1.235
        assert round_usd(12.3456, 2) == 12.35
        assert round_ratio(0.12345, 3) == 0.123
