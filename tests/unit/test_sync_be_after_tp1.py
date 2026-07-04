from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from main import _sync_be_stop_after_tp1


def test_sync_be_stop_after_tp1_places_be_before_tp2(monkeypatch) -> None:
    monkeypatch.setattr("main.settings.MODE", "live")
    monkeypatch.setattr("main.settings.EXCHANGE_TP2_AFTER_TP1", True)
    order: list[str] = []
    engine = MagicMock()
    engine.sync_stop_loss.side_effect = lambda _pos: order.append("be") or True

    def _tp2(_engine, _pos) -> bool:
        order.append("tp2")
        return True

    monkeypatch.setattr("main.ensure_exchange_tp2_after_tp1", _tp2)
    monkeypatch.setattr("main._sync_open_position_journal", lambda _pos: None)

    _sync_be_stop_after_tp1(engine, MagicMock())

    assert order == ["be", "tp2"]
