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
from app.monitoring.messages import format_mode_event_line


class TestTelegramPositionLifecycleNotificationsIntegration:
    def test_telegram_full_lifecycle_sequence_includes_breakeven(self) -> None:
        sequence = [
            (
                "OPEN",
                "Strategy: Liquidity | Setup: Liquidity Sweep Reversal | Entry: 250.10 | "
                "Size: 330.13 USDT | Margin: 47.16 | "
                "SL: 248.66 (-0.58%) | TP1: 252.60 (1.00%) | TP2: 255.10 (2.00%) | "
                "TP3: 257.60 (3.00%) | Risk: 1.90 USDT",
            ),
            ("TP1 HIT", "Price: 252.60 | Closed: 165.07 USDT | Remaining: 165.07 USDT | PNL: +1.65 USDT"),
            ("BREAKEVEN", "SL → Entry (250.10) | Remaining: 165.07 USDT | Risk: 0 USDT"),
            ("TP2 HIT", "Price: 255.10 | Closed: 99.04 USDT | Remaining: 66.03 USDT | PNL: +1.98 USDT"),
            ("TP3 HIT", "Price: 257.60 | Closed: 66.03 USDT | Remaining: 0.00 USDT | PNL: +1.98 USDT"),
            (
                "CLOSE",
                "Size: 330.13 USDT | Margin: 47.16 USDT | Entry: 250.10 | "
                "Exit: 257.60 | Duration: 20.7 min | Total PNL: +5.61 USDT",
            ),
        ]

        expected_lines = [
            format_mode_event_line("demo", "TAOUSDT", "LONG", event, payload)
            for event, payload in sequence
        ]

        with patch("app.monitoring.events.send_alert", return_value=True) as mock_send_alert:
            for event, payload in sequence:
                line = emit_mode_event("demo", "TAOUSDT", "LONG", event, payload)
                assert line == format_mode_event_line("demo", "TAOUSDT", "LONG", event, payload)

        alerted_lines = [call.args[0] for call in mock_send_alert.call_args_list]
        assert alerted_lines == expected_lines
        assert len(alerted_lines) == 6
