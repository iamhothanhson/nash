from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import OrderPlan

try:
    from app.signal_builder.config import TP_CONFIG
    from app.signal_builder.models import TradeSignal
    from app.signal_builder.take_profit import resolve_tp1_tp2_prices
except ImportError:  # pragma: no cover - fallback for script-style execution
    from signal_builder.config import TP_CONFIG
    from signal_builder.models import TradeSignal
    from signal_builder.take_profit import resolve_tp1_tp2_prices

@dataclass(slots=True)
class DailyState:
    entries_today: int = 0
    last_symbol: str | None = None
    last_timestamp: Any | None = None

    def register_entry(self, symbol: str | None = None, timestamp: Any | None = None) -> None:
        self.entries_today += 1
        self.last_symbol = symbol
        self.last_timestamp = timestamp


def risk_controls_allow(*_args: Any, **_kwargs: Any) -> tuple[bool, list[str]]:
    return True, []

class OrderPlanner:

    @staticmethod
    def build_order_plan(signal: TradeSignal | Any, risk: Any | None = None, **kwargs: Any) -> OrderPlan | None:
        if signal is None:
            return None

        entry = float(getattr(signal, "entry", None) if getattr(signal, "entry", None) is not None else kwargs.get("entry", 0.0))
        stop_loss = float(getattr(signal, "stop_loss", None) if getattr(signal, "stop_loss", None) is not None else kwargs.get("stop_loss", 0.0))

        if entry <= 0 or stop_loss <= 0:
            return None

        direction = OrderPlanner._stringify(getattr(signal, "direction", kwargs.get("direction", "long")))
        direction_key = str(direction).lower()

        sl_distance = abs(entry - stop_loss) / entry if entry > 0 else 0.0
        if sl_distance <= 0:
            return None

        balance = OrderPlanner._resolve_balance(signal, kwargs)
        risk_per_trade = OrderPlanner._resolve_risk_per_trade(signal, kwargs)
        risk_amount = OrderPlanner._resolve_risk_amount(risk, kwargs, balance, risk_per_trade)
        risk_percent = OrderPlanner._resolve_risk_percent(risk, kwargs, risk_per_trade)

        position_notional = OrderPlanner._resolve_position_notional(risk, kwargs, risk_amount, sl_distance)
        notional = float(kwargs.get("notional", 0.0) or 0.0)
        if notional <= 0:
            notional = position_notional

        quantity = float(kwargs.get("qty", 0.0) or 0.0)
        if quantity <= 0 and notional > 0:
            quantity = notional / entry if entry > 0 else 0.0
        if quantity <= 0 and position_notional > 0:
            quantity = position_notional / entry if entry > 0 else 0.0

        max_notional_account_cap = kwargs.get("max_notional_account_cap")
        if max_notional_account_cap is not None:
            cap = float(max_notional_account_cap)
            if cap > 0 and notional > cap:
                notional = cap
                quantity = notional / entry if entry > 0 else 0.0

        available_balance = kwargs.get("available_balance")
        if available_balance is not None:
            available = float(available_balance)
            if available > 0 and notional > available:
                notional = available
                quantity = notional / entry if entry > 0 else 0.0

        return OrderPlan(
            symbol=OrderPlanner._stringify(kwargs.get("symbol") or getattr(signal, "symbol", "UNKNOWN")),
            direction=direction,
            entry=entry,
            stop_loss=stop_loss,
            tp1=signal.tp1,
            tp2=signal.tp2,
            tp3=signal.tp3,
            qty=quantity,
            notional=notional,
            risk_amount=risk_amount,
            risk_percent=risk_percent,
            setup_type=OrderPlanner._stringify(getattr(signal, "setup_type", kwargs.get("setup_type", ""))),
            setup_grade=OrderPlanner._stringify(getattr(signal, "setup_grade", kwargs.get("setup_grade", ""))),
            setup_score=float(getattr(signal, "setup_score", kwargs.get("setup_score", 0.0)) or 0.0),
            confirmation_mode=OrderPlanner._stringify(getattr(signal, "confirmation_mode", kwargs.get("confirmation_mode", ""))),
            strategy_family=OrderPlanner._stringify(getattr(signal, "strategy_family", kwargs.get("strategy_family", ""))),
            r_multiple=float(getattr(signal, "r_multiple", kwargs.get("r_multiple", 1.0)) or 1.0),
            market_structure=OrderPlanner._stringify(getattr(signal, "market_structure", kwargs.get("market_structure", "Range"))),
            market_regime_detail=getattr(signal, "market_regime_detail", kwargs.get("market_regime_detail")),
        )

    @staticmethod
    def _resolve_balance(signal: Any, kwargs: dict[str, Any]) -> float:
        if kwargs.get("balance") is not None:
            return float(kwargs.get("balance"))

        virtual = kwargs.get("virtual")
        if virtual is not None and hasattr(virtual, "balance"):
            return float(getattr(virtual, "balance"))

        return float(getattr(signal, "balance", None) or 1000.0)


    @staticmethod
    def _resolve_risk_per_trade(signal: Any, kwargs: dict[str, Any]) -> float:
        explicit = kwargs.get("risk_per_trade")
        if explicit is not None:
            return float(explicit)

        signal_risk = getattr(signal, "signal_risk_per_trade", None)
        if signal_risk is not None:
            return float(signal_risk)

        multiplier = kwargs.get("risk_multiplier")
        if multiplier is not None:
            return float(multiplier)

        return 0.01


    @staticmethod
    def _resolve_risk_amount(risk: Any, kwargs: dict[str, Any], balance: float, risk_per_trade: float) -> float:
        if risk is not None and hasattr(risk, "risk_amount"):
            return float(getattr(risk, "risk_amount"))

        if kwargs.get("risk_amount") is not None:
            return float(kwargs.get("risk_amount"))

        if balance > 0:
            return balance * risk_per_trade

        return 0.0


    @staticmethod
    def _resolve_position_notional(risk: Any, kwargs: dict[str, Any], risk_amount: float, sl_distance: float) -> float:
        if risk is not None and hasattr(risk, "position_notional"):
            return float(getattr(risk, "position_notional"))

        if kwargs.get("position_notional") is not None:
            return float(kwargs.get("position_notional"))

        if kwargs.get("notional") is not None:
            return float(kwargs.get("notional"))

        if risk_amount > 0 and sl_distance > 0:
            return risk_amount / sl_distance

        return 0.0


    @staticmethod
    def _resolve_risk_percent(risk: Any, kwargs: dict[str, Any], risk_per_trade: float) -> float:
        if risk is not None and hasattr(risk, "risk_percent"):
            return float(getattr(risk, "risk_percent"))

        if kwargs.get("risk_percent") is not None:
            return float(kwargs.get("risk_percent"))

        return risk_per_trade * 100.0


    @staticmethod
    def _default_take_profit(entry: float, stop_loss: float, direction: str, multiplier: float) -> float:
        if entry <= 0 or stop_loss <= 0:
            return entry

        distance = abs(entry - stop_loss)
        if direction == "short":
            return entry - distance * multiplier
        return entry + distance * multiplier

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)
