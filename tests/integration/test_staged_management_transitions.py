from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
APP_PATH = PROJECT_ROOT / "app"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from app.position_management.staged import ManagedPosition, apply_staged_management


def _pnl(direction: str, entry: float, exit_px: float, qty: float) -> float:
    if direction == "LONG":
        return (exit_px - entry) * qty
    return (entry - exit_px) * qty


def _df15(*, break_last: bool = False) -> pd.DataFrame:
    rows = []
    for i in range(36):
        low = 100.0 + i * 0.35
        high = low + 1.1
        close = high - 0.15
        rows.append({"open": low, "high": high, "low": low, "close": close, "volume": 1.0})
    if break_last:
        rows[-1]["close"] = rows[-2]["low"] - 1.0
        rows[-1]["low"] = rows[-1]["close"]
        rows[-1]["high"] = rows[-2]["low"]
    return pd.DataFrame(rows)


class TestStagedManagementTransitionsIntegration:
    def _pos(self) -> ManagedPosition:
        return ManagedPosition(
            symbol="TAOUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=1.0,
            entry=100.0,
            stop_loss=99.0,
            current_stop_loss=99.0,
            tp1=101.0,
            tp2=102.0,
            tp3=0.0,
        )

    def test_tp1_tp2_then_runner_structure_exit(self) -> None:
        pos = self._pos()
        df15 = _df15()
        fills = apply_staged_management(pos, high=101.2, low=99.8, now_ts=800.0, pnl_fn=_pnl, df15=df15)
        assert any(f.tag == "TP1 HIT" for f in fills)
        assert pos.qty_open > 0.0

        fills2 = apply_staged_management(pos, high=102.2, low=101.0, now_ts=850.0, pnl_fn=_pnl, df15=df15)
        assert any(f.tag == "TP2 HIT" for f in fills2)
        assert pos.qty_open > 0.0

        apply_staged_management(pos, high=103.0, low=102.0, now_ts=900.0, pnl_fn=_pnl, df15=df15)
        fills3 = apply_staged_management(
            pos,
            high=103.0,
            low=99.0,
            now_ts=1800.0,
            pnl_fn=_pnl,
            df15=_df15(break_last=True),
        )
        assert any(f.tag == "TP3 HIT" for f in fills3)
        assert pos.closed
        assert pos.qty_open == 0.0

    def test_sl_hits_and_forces_close(self) -> None:
        pos = self._pos()
        fills = apply_staged_management(pos, high=100.2, low=98.9, pnl_fn=_pnl)
        assert any(f.tag == "SL HIT" for f in fills)
        assert any(f.tag == "CLOSE" for f in fills)
        assert pos.closed
        assert pos.qty_open == 0.0

    def test_same_bar_tp1_before_tp2_fill_order(self) -> None:
        pos = ManagedPosition(
            symbol="TAOUSDT",
            direction="LONG",
            qty_total=1.0,
            qty_open=1.0,
            entry=280.0,
            stop_loss=278.0,
            current_stop_loss=278.0,
            tp1=285.0,
            tp2=290.0,
            tp3=0.0,
        )
        fills = apply_staged_management(pos, high=291.0, low=279.0, pnl_fn=_pnl)
        tags = [f.tag for f in fills]
        assert tags.index("TP1 HIT") < tags.index("TP2 HIT")
        assert pos.hit_tp1 and pos.hit_tp2

    def test_tp2_hit_logs_sl_move(self, monkeypatch) -> None:
        from app.position_management import staged as staged_mod

        messages: list[str] = []
        monkeypatch.setattr(staged_mod, "log", lambda m: messages.append(str(m)))

        pos = self._pos()
        pos.hit_tp1 = True
        pos.current_stop_loss = 100.4
        pos.qty_open = 0.5
        fills = apply_staged_management(
            pos,
            high=102.2,
            low=101.5,
            now_ts=850.0,
            pnl_fn=_pnl,
            df15=_df15(),
        )
        assert any(f.tag == "TP2 HIT" for f in fills)
        assert float(pos.current_stop_loss) >= 100.4
        assert messages == []
