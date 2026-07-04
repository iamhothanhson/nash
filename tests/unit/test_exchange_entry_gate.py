from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from execution.exchange_entry_gate import should_block_exchange_entry


def test_allows_stack_when_tracked_below_cap() -> None:
    client = MagicMock()
    client.use_hedge_position_side.return_value = True
    with patch("execution.exchange_entry_gate.max_opened_positions_for", return_value=2):
        blocked, _ = should_block_exchange_entry(
            client,
            "TAOUSDT",
            {"TAOUSDT": 1},
            direction="LONG",
        )
    assert blocked is False
    client.has_open_position_size.assert_not_called()


def test_blocks_orphan_when_tracked_zero_but_exchange_has_size() -> None:
    client = MagicMock()
    client.use_hedge_position_side.return_value = True
    client.get_position_amount.return_value = 0.035
    client.open_position_summary.return_value = "LONG=0.03500000"
    blocked, why = should_block_exchange_entry(
        client,
        "TAOUSDT",
        {"TAOUSDT": 0},
        direction="LONG",
    )
    assert blocked is True
    assert "untracked" in why


def test_blocks_at_per_symbol_cap() -> None:
    client = MagicMock()
    blocked, why = should_block_exchange_entry(
        client,
        "TAOUSDT",
        {"TAOUSDT": 2},
        direction="LONG",
    )
    assert blocked is True
    assert "per-symbol cap" in why
