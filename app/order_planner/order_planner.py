from __future__ import annotations

from typing import Any

from app.core.config import TP_CLOSE_PCT
from app.core import settings
from .models import OrderPlan

try:
    from exchange.client import BinanceFuturesClient
except ImportError:
    BinanceFuturesClient = None


class OrderPlanner:
    @staticmethod
    def _available_balance() -> float:
        if settings.MODE not in ("live", "demo") or BinanceFuturesClient is None:
            return 0.0

        try:
            account = BinanceFuturesClient().get_account()
            return float(account.get("availableBalance", 0))
        except Exception:
            return 0.0

    @staticmethod
    def build_order_plan(
        signal: Any,
        risk: Any | None = None,
        pipeline_stats: Any = None,
        **_: Any,
    ) -> OrderPlan | None:

        if signal is None or risk is None:
            return None

        entry = float(signal.entry)
        stop_loss = float(signal.stop_loss)

        sl_distance = OrderPlanner._stop_loss_distance(entry, stop_loss)
        if not sl_distance:
            return None

        position_notional = float(risk.position_notional)
        risk_amount = float(risk.risk_amount)

        if position_notional <= 0 or risk_amount <= 0:
            return None

        quantity = float(risk.quantity) or position_notional / entry
        if quantity <= 0:
            return None

        # Cap by available margin
        result = OrderPlanner._cap_position_size(position_notional, quantity)
        if result is None:
            return None

        position_notional, quantity = result

        tp1_qty = quantity * TP_CLOSE_PCT["tp_1"] / 100
        margin = position_notional / settings.LEVERAGE

        if pipeline_stats:
            pipeline_stats.order_planned += 1

        return OrderPlan(
            symbol=signal.symbol.upper(),
            direction=signal.direction.upper(),
            entry=entry,
            qty=quantity,
            stop_loss=stop_loss,
            tp1=signal.tp1,

            tp1_pct=signal.tp1_pct,
            tp1_qty=tp1_qty,
            tp2_qty=quantity - tp1_qty,
            notional=position_notional,
            margin_usdt=margin,
            risk_amount=risk_amount,
            risk_percent=risk_amount / (position_notional * sl_distance) * 100,
            risk_per_trade=risk.risk_per_trade,
            risk_multiplier=risk.risk_multiplier,
            setup_type=signal.setup_type,
            setup_score=signal.setup_score,
            setup_grade=signal.setup_grade,
            confirmation_mode=signal.confirmation_mode,
            strategy_family=signal.strategy_family,
            market_state=signal.market_state,
            features=signal.features,
            trailing_stop=getattr(signal, "trailing_stop", None),
        )

    @staticmethod
    def _stop_loss_distance(entry: float, stop_loss: float):
        if entry <= 0 or stop_loss <= 0:
            return None

        sl_distance = abs(entry - stop_loss) / entry
        if sl_distance <= 0:
            return None

        return sl_distance

    @staticmethod
    def _cap_position_size(
        position_notional: float,
        quantity: float,
    ) -> tuple[float, float] | None:
        available = OrderPlanner._available_balance()
        if available <= 0:
            return None

        max_notional = available * settings.LEVERAGE
        if position_notional <= max_notional:
            return position_notional, quantity

        scale = max_notional / position_notional
        position_notional *= scale
        quantity *= scale

        if position_notional < settings.MIN_POSITION_NOTIONAL:
            return None

        return position_notional, quantity