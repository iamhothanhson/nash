from __future__ import annotations
from typing import Any

from config import settings
from .config import TP_CLOSE_PCT
from .models import OrderPlan

try:
    from exchange.client import BinanceFuturesClient
except ImportError:
    BinanceFuturesClient = None  # type: ignore[assignment,misc]


def risk_controls_allow(*_args: Any, **_kwargs: Any) -> tuple[bool, list[str]]:
    return True, []


class OrderPlanner:

    @staticmethod
    def _available_balance() -> float:
        if settings.MODE in ("live", "demo") and BinanceFuturesClient is not None:
            try:
                client = BinanceFuturesClient()
                account = client.get_account()
                return float(account.get("availableBalance", 0))
            except Exception:
                pass
        return 0.0

    @staticmethod
    def build_order_plan(signal: Any, risk: Any | None = None, **kwargs: Any) -> OrderPlan | None:
        if signal is None:
            return None

        entry = float(getattr(signal, "entry", 0.0))
        stop_loss = float(getattr(signal, "stop_loss", 0.0))

        if entry <= 0 or stop_loss <= 0:
            return None

        direction = str(getattr(signal, "direction", "LONG")).upper()
        sl_distance = abs(entry - stop_loss) / entry
        if sl_distance <= 0:
            return None

        risk_amount = float(getattr(risk, "risk_amount", 0.0))
        position_notional = float(getattr(risk, "position_notional", 0.0))
        quantity = float(getattr(risk, "quantity", 0.0))

        if risk_amount <= 0:
            return None
        if quantity <= 0 or position_notional <= 0:
            quantity = position_notional / entry if entry > 0 and position_notional > 0 else 0.0
            if quantity <= 0:
                return None

        # ---- balance check: cap or reject ----
        available = OrderPlanner._available_balance()
        required_margin = position_notional / float(settings.LEVERAGE)
        if available > 0 and required_margin > available:
            ratio = available / required_margin
            position_notional = position_notional * ratio
            quantity = quantity * ratio
            if position_notional < float(getattr(settings, "MIN_POSITION_NOTIONAL", 5.0)) or quantity <= 0:
                return None

        tp1_qty = quantity * TP_CLOSE_PCT.get("tp_1", 0) / 100.0
        tp2_qty = quantity * TP_CLOSE_PCT.get("tp_2", 0) / 100.0
        tp3_qty = quantity * TP_CLOSE_PCT.get("tp_3", 0) / 100.0

        risk_percent=risk_amount / (position_notional * sl_distance) * 100.0 if position_notional > 0 and sl_distance > 0 else 0.0

        return OrderPlan(
            symbol=str(getattr(signal, "symbol", "UNKNOWN")).strip().upper(),
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            tp1=float(getattr(signal, "tp1", 0.0)),
            tp2=float(getattr(signal, "tp2", 0.0)),
            tp3=float(getattr(signal, "tp3", 0.0)),
            qty=quantity,
            tp1_qty=tp1_qty,
            tp2_qty=tp2_qty,
            tp3_qty=tp3_qty,
            notional=position_notional,
            risk_amount=risk_amount,
            risk_percent=risk_percent,
            setup_type=str(getattr(signal, "setup_type", "")),
            setup_grade=str(getattr(signal, "setup_grade", "")),
            setup_score=float(getattr(signal, "setup_score", 0.0)),
            confirmation_mode=str(getattr(signal, "confirmation_mode", "")),
            strategy_family=str(getattr(signal, "strategy_family", "")),
            r_multiple=float(getattr(signal, "r_multiple", 1.0)),
        )

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
