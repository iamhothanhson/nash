from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.monitoring.events import emit_mode_event


class TestFullLifecycleNotificationsRegression:
    def test_full_lifecycle_notification_order(self) -> None:
        sequence = [
            (
                "OPEN",
                "Strategy: Trend Following | Setup: Breakout | Entry: 250.00 | "
                "Size: 250.00 USDT | Margin: 35.71 | "
                "SL: 248.50 (-0.60%) | TP1: 252.50 (1.00%) | TP2: 255.00 (2.00%) | "
                "TP3: 257.50 (3.00%) | Risk: 1.50 USDT",
            ),
            ("TP1 HIT", "Price: 252.00 | Closed: 125.00 USDT | Remaining: 125.00 USDT | PNL: +1.00 USDT"),
            ("BREAKEVEN", "SL → Entry (250.00) | Remaining: 125.00 USDT | Risk: 0 USDT"),
            ("TP2 HIT", "Price: 254.00 | Closed: 75.00 USDT | Remaining: 50.00 USDT | PNL: +1.20 USDT"),
            ("TP3 HIT", "Price: 256.00 | Closed: 50.00 USDT | Remaining: 0.00 USDT | PNL: +1.20 USDT"),
            ("CLOSE", "price=253.00 | qty_closed=0.500 | qty_remaining=0.000 | pnl=+1.80"),
        ]
        with patch("app.monitoring.events.log") as mock_log, patch(
            "app.monitoring.events.send_alert"
        ) as mock_send_alert:
            for event, payload in sequence:
                emit_mode_event("demo", "TAOUSDT", "LONG", event, payload)

        logged = [c.args[0] for c in mock_log.call_args_list]
        alerted = [c.args[0] for c in mock_send_alert.call_args_list]
        assert logged == alerted
        assert len(logged) == 6
        assert "[OPEN] TAOUSDT [LONG]" in logged[0]
        assert "[TP1 HIT] TAOUSDT [LONG]" in logged[1]
        assert "[BREAKEVEN] TAOUSDT [LONG]" in logged[2]
        assert "[TP2 HIT] TAOUSDT [LONG]" in logged[3]
        assert "[TP3 HIT] TAOUSDT [LONG]" in logged[4]
        assert "[CLOSE] TAOUSDT [LONG]" in logged[5]
