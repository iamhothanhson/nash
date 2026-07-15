from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from exchange.client import BinanceFuturesClient
from config import settings


RUNTIME_POSITIONS = Path("data/runtime/positions.json")
POSITION_HISTORY_DIR = Path("data/position_history")


class PositionManager:
    """Poll order status by ID, place delayed TP2/TP3, persist to positions.json."""

    def __init__(self) -> None:
        self._client: BinanceFuturesClient | None = None

    @property
    def client(self) -> BinanceFuturesClient:
        if self._client is None:
            self._client = BinanceFuturesClient()
        return self._client

    # ------------------------------------------------------------------
    # JSON I/O
    # ------------------------------------------------------------------

    def _read(self) -> dict[str, Any]:
        if not RUNTIME_POSITIONS.exists():
            return {}
        raw = RUNTIME_POSITIONS.read_text(encoding="utf-8")
        if not raw.strip():
            return {}
        return json.loads(raw)

    def _write(self, data: dict[str, Any]) -> None:
        RUNTIME_POSITIONS.parent.mkdir(parents=True, exist_ok=True)
        RUNTIME_POSITIONS.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")

    # ------------------------------------------------------------------
    # main loop
    # ------------------------------------------------------------------

    def update_trailing_stops(self, symbols: list[str]) -> None:
        if settings.MODE not in ("live", "demo"):
            return

        pos = self._read()
        if not pos or pos.get("status") != "Open":
            return

        sym = pos.get("symbol", "")
        if sym not in [s.strip().upper() for s in symbols]:
            return

        self._check_orders(pos)

    def _check_orders(self, pos: dict[str, Any]) -> None:
        sym = pos["symbol"]
        changed = False

        sl = pos.get("stop_loss", {})
        tps = pos.get("take_profit", [])
        tp1 = tps[0] if len(tps) > 0 else {}
        tp2 = tps[1] if len(tps) > 1 else {}
        tp3 = tps[2] if len(tps) > 2 else {}

        # --- 1. SL ---
        sl_id = sl.get("sl_order_id")
        if sl_id and not sl.get("sl_hit"):
            resp = self.client.get_order(sym, sl_id)
            if resp.get("status") == "FILLED":
                sl["sl_hit"] = True
                pos["status"] = "Closed"
                pos["closed"] = _now()
                pos["closed_reason"] = "SL HIT"
                changed = True

        if pos["status"] != "Open":
            self._archive_and_clear(pos)
            return

        # --- 2. TP1 ---
        tp1_id = tp1.get("tp1_order_id")
        if tp1_id and not tp1.get("tp1_hit"):
            resp = self.client.get_order(sym, tp1_id)
            if resp.get("status") == "FILLED":
                tp1["tp1_hit"] = True
                self._replace_sl(sym, pos["entry"], pos)
                self._place_tp2(tp2, pos)
                changed = True

        # --- 3. TP2 ---
        tp2_id = tp2.get("tp2_order_id")
        if tp2_id and not tp2.get("tp2_hit"):
            resp = self.client.get_order(sym, tp2_id)
            if resp.get("status") == "FILLED":
                tp2["tp2_hit"] = True
                tp1_price = tp1.get("price", pos["entry"])
                self._replace_sl(sym, tp1_price, pos)
                self._place_tp3(tp3, pos)
                changed = True

        # --- 4. TP3 ---
        tp3_id = tp3.get("tp3_order_id")
        if tp3_id and not tp3.get("tp3_hit"):
            resp = self.client.get_order(sym, tp3_id)
            if resp.get("status") == "FILLED":
                tp3["tp3_hit"] = True
                pos["status"] = "Closed"
                pos["closed"] = _now()
                pos["closed_reason"] = "TP3 FILLED"
                changed = True

        if pos["status"] != "Open":
            if changed:
                self._archive_and_clear(pos)
            return

        # --- update PnL ---
        account = self.client.get_account()
        for p in account.get("positions", []):
            if p.get("symbol") == sym:
                pos["pnl_usdt"] = round(float(p.get("unRealizedProfit", 0)), 2)
                break

        if changed:
            self._write(pos)

    # ------------------------------------------------------------------
    # trailing actions
    # ------------------------------------------------------------------

    def _replace_sl(self, symbol: str, price: float, pos: dict[str, Any]) -> None:
        self.client.cancel_all_orders(symbol)
        side = "SELL" if pos["side"] == "LONG" else "BUY"
        ps = pos.get("pos_side")
        resp = self.client.create_conditional_stop_market_order(
            symbol=symbol, side=side,
            stop_price=self.client.normalize_price(symbol, price),
            close_position=True, position_side=ps,
        )
        sl = pos.get("stop_loss", {})
        sl["sl_order_id"] = resp.get("orderId")
        sl["sl_hit"] = False

    def _place_tp2(self, tp2: dict[str, Any], pos: dict[str, Any]) -> None:
        qty_pct = tp2.get("tp2_partial_close", 30)
        qty = qty_pct / 100 * pos["entry_qty"]
        side = "SELL" if pos["side"] == "LONG" else "BUY"
        ps = pos.get("pos_side")
        resp = self._place_tp_order(pos["symbol"], tp2["price"], qty, side, ps)
        if resp:
            tp2["tp2_order_id"] = resp.get("orderId")

    def _place_tp3(self, tp3: dict[str, Any], pos: dict[str, Any]) -> None:
        qty_pct = tp3.get("tp3_partial_close", 20)
        qty = qty_pct / 100 * pos["entry_qty"]
        side = "SELL" if pos["side"] == "LONG" else "BUY"
        ps = pos.get("pos_side")
        resp = self._place_tp_order(pos["symbol"], tp3["price"], qty, side, ps)
        if resp:
            tp3["tp3_order_id"] = resp.get("orderId")

    def _archive_and_clear(self, pos: dict[str, Any]) -> None:
        """Move closed position to monthly history, clear positions.json."""
        now = datetime.now(timezone.utc)
        month_file = POSITION_HISTORY_DIR / f"{now.strftime('%m-%Y')}.json"
        POSITION_HISTORY_DIR.mkdir(parents=True, exist_ok=True)

        history = []
        if month_file.exists():
            raw = month_file.read_text(encoding="utf-8")
            if raw.strip():
                history = json.loads(raw)
                if not isinstance(history, list):
                    history = [history]

        history.append(pos)
        month_file.write_text(json.dumps(history, indent=2, default=str), encoding="utf-8")

        RUNTIME_POSITIONS.write_text("{}\n", encoding="utf-8")

    def _place_tp_order(self, symbol: str, price: float, qty: float, side: str, ps: str | None) -> dict[str, Any] | None:
        if price <= 0 or qty <= 0:
            return None
        qty = self.client.normalize_qty(symbol, qty)
        if qty <= 0:
            return None
        return self.client.place_order({
            "symbol": symbol, "side": side,
            "type": "TAKE_PROFIT_MARKET",
            "stopPrice": self.client.normalize_price(symbol, price),
            "quantity": qty,
            "workingType": "MARK_PRICE",
            **({"positionSide": ps} if ps else {}),
        })


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%b-%d-%Y %H:%M:%S")
