from __future__ import annotations

from typing import Any

from config import settings
from exchange.client import BinanceFuturesClient
from exchange.utils import position_side_for_direction
from exchange.exceptions import BinanceOrderError
from monitoring.logger import log
from order_planner.models import OrderPlan


class Executor:
    """Places entry, stop-loss and take-profit orders on Binance Futures."""

    _client: BinanceFuturesClient | None = None

    @classmethod
    def _get_client(cls) -> BinanceFuturesClient:
        if cls._client is None:
            cls._client = BinanceFuturesClient()
        return cls._client

    @classmethod
    def execute(cls, plan: OrderPlan) -> dict[str, Any]:
        if settings.MODE not in ("live", "demo"):
            log(f"[EXECUTOR] {plan.symbol} | skip (mode={settings.MODE})")
            return {"status": "skipped", "mode": settings.MODE}

        client = cls._get_client()
        sym = plan.symbol.strip().upper()
        direction = plan.direction.upper()
        hedge = settings.BINANCE_POSITION_MODE == "hedge"

        side = "BUY" if direction == "LONG" else "SELL"
        opp = "SELL" if side == "BUY" else "BUY"
        ps = position_side_for_direction(direction, hedge_mode=hedge)

        qty = client.normalize_qty(sym, plan.qty)
        if qty <= 0:
            raise BinanceOrderError(-1, f"Invalid quantity {plan.qty} after normalization")

        # ---- check available balance ----
        account = client.get_account()
        available_balance = float(account.get("availableBalance", 0))
        required_margin = plan.notional / float(settings.LEVERAGE)
        if available_balance < required_margin:
            msg = (
                f"Insufficient available balance: have {available_balance:.2f} USDT, "
                f"need ~{required_margin:.2f} USDT margin for {plan.notional:.2f} USDT position"
            )
            log(f"[EXECUTOR] {sym} | {msg}")
            return {"status": "rejected", "reason": msg}

        log(f"[EXECUTOR] {sym} | ENTER {side} qty={qty}")
        entry_resp = client.place_order({
            "symbol": sym,
            "side": side,
            "type": "MARKET",
            "quantity": qty,
            "newOrderRespType": "RESULT",
            **({"positionSide": ps} if ps else {}),
        })
        entry_id = entry_resp.get("orderId")
        fill_price = float(entry_resp.get("avgPrice", plan.entry))
        filled_qty = sum(float(f["qty"]) for f in entry_resp.get("fills", [])) or qty
        log(f"[EXECUTOR] {sym} | FILLED orderId={entry_id} price={fill_price} qty={filled_qty}")

        # ---- stop loss (STOP_MARKET, closePosition) ----
        sl_price = client.normalize_price(sym, plan.stop_loss)
        log(f"[EXECUTOR] {sym} | SL {opp} stopPrice={sl_price}")
        client.place_order({
            "symbol": sym,
            "side": opp,
            "type": "STOP_MARKET",
            "stopPrice": sl_price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
            **({"positionSide": ps} if ps else {}),
        })

        # ---- TP1 (TAKE_PROFIT_LIMIT) ----
        tp1_price = client.normalize_price(sym, plan.tp1)
        tp1_qty = client.normalize_qty(sym, plan.tp1_qty or filled_qty * settings.EXECUTOR_TP1_FRAC)
        if tp1_qty > 0:
            log(f"[EXECUTOR] {sym} | TP1 {opp} price={tp1_price} qty={tp1_qty}")
            client.place_order({
                "symbol": sym,
                "side": opp,
                "type": "TAKE_PROFIT_LIMIT",
                "price": tp1_price,
                "stopPrice": tp1_price,
                "quantity": tp1_qty,
                "timeInForce": "GTC",
                "workingType": "MARK_PRICE",
                **({"positionSide": ps} if ps else {}),
            })

        result = {
            "status": "placed",
            "symbol": sym,
            "direction": direction,
            "entry_order_id": entry_id,
            "entry_price": fill_price,
            "filled_qty": filled_qty,
        }
        log(f"[EXECUTOR] {sym} | Done — {result}")
        return result
