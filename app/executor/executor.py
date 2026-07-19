from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from config import settings
from exchange.client import BinanceFuturesClient
from exchange.utils import position_side_for_direction
from exchange.exceptions import BinanceOrderError
from order_planner.models import OrderPlan
from position.archive import save_runtime_position
from analysis.collect_position_metrics import build_entry_snapshot, save_entry_snapshot


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
        sl_resp = client.place_order({
            "symbol": sym,
            "side": opp,
            "type": "STOP_MARKET",
            "stopPrice": sl_price,
            "closePosition": "true",
            "workingType": "MARK_PRICE",
            **({"positionSide": ps} if ps else {}),
        })
        sl_order_id = sl_resp.get("orderId")

        # ---- TP1 (TAKE_PROFIT_MARKET) ----
        tp1_price = client.normalize_price(sym, plan.tp1)
        tp1_qty = client.normalize_qty(sym, plan.tp1_qty or filled_qty * settings.EXECUTOR_TP1_FRAC)
        tp1_order_id = None
        if tp1_qty > 0:
            tp1_resp = client.place_order({
                "symbol": sym,
                "side": opp,
                "type": "TAKE_PROFIT_MARKET",
                "stopPrice": tp1_price,
                "quantity": tp1_qty,
                "workingType": "MARK_PRICE",
                **({"positionSide": ps} if ps else {}),
            })
            tp1_order_id = tp1_resp.get("orderId")

        leverage = float(settings.LEVERAGE or 1)
        size_usdt = plan.notional or filled_qty * fill_price
        margin_usdt = size_usdt / leverage

        sl_pct = ((fill_price - plan.stop_loss) / fill_price) * 100 if direction == "LONG" else ((plan.stop_loss - fill_price) / fill_price) * 100
        tp1_pct = ((plan.tp1 - fill_price) / fill_price) * 100 if direction == "LONG" else ((fill_price - plan.tp1) / fill_price) * 100
        tp2_pct = ((plan.tp2 - fill_price) / fill_price) * 100 if direction == "LONG" else ((fill_price - plan.tp2) / fill_price) * 100
        tp3_pct = ((plan.tp3 - fill_price) / fill_price) * 100 if direction == "LONG" else ((fill_price - plan.tp3) / fill_price) * 100

        entry_snapshot = build_entry_snapshot(
            plan.market_state, plan.features,
            symbol=sym, side=direction, strategy_setup=plan.setup_type,
        )
        save_entry_snapshot(entry_snapshot)

        pos_data = {
            "status": "Open",
            "symbol": sym,
            "side": direction,
            "strategy": "trend_following",
            "setup": plan.setup_type,
            "size_usdt": round(size_usdt, 2),
            "margin_usdt": round(margin_usdt, 2),
            "entry": fill_price,
            "entry_qty": filled_qty,
            "pos_side": ps,
            "stop_loss": {
                "price": plan.stop_loss,
                "percent": round(sl_pct, 2),
                "risk_usdt": plan.risk_amount,
                "sl_order_id": sl_order_id,
                "sl_hit": False,
            },
            "take_profit": [
                {
                    "tp1_partial_close": 50.0,
                    "tp1_hit": False,
                    "price": plan.tp1,
                    "percent": round(tp1_pct, 2),
                    "tp1_order_id": tp1_order_id,
                },
                {
                    "tp2_partial_close": 30.0,
                    "tp2_hit": False,
                    "price": plan.tp2,
                    "percent": round(tp2_pct, 2),
                    "tp2_order_id": None,
                },
                {
                    "tp3_partial_close": 20.0,
                    "tp3_hit": False,
                    "price": plan.tp3,
                    "percent": round(tp3_pct, 2),
                    "tp3_order_id": None,
                },
            ],
            "pnl_usdt": 0.0,
            "exchange_pnl_usdt": None,
            "balance_usdt": client.get_balance("USDT"),
            "closed_reason": None,
            "opened": datetime.now(timezone.utc).strftime("%b-%d-%Y %H:%M:%S"),
            "closed": None,
        }

        save_runtime_position(pos_data)
        log(f"[EXECUTOR] {sym} | Position saved to runtime/positions.json")

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
