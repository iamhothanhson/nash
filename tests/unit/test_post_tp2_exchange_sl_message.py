from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from monitoring.messages import format_post_tp2_exchange_sl_placed_line


@pytest.mark.unit
def test_format_post_tp2_exchange_sl_placed_line() -> None:
    line = format_post_tp2_exchange_sl_placed_line(
        symbol="RENDERUSDT",
        order_id=1000001925761069,
        stop_price=1.568,
        size_usdt=10.35,
        price_decimals=3,
    )
    assert line == (
        "[SL MOVE] RENDERUSDT | Placed Conditional Stop Loss orderId=1000001925761069 "
        "Price=1.568 Size USDT: 10.35"
    )
