# risk_manager.py

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RiskResult:
    allowed: bool
    risk_amount: float
    position_notional: float
    quantity: float
    reason: str = ""


class RiskManager:
    def __init__(
        self,
        *,
        balance: float,
        max_position_notional: float | None = None,
        min_position_notional: float = 5.0,
    ) -> None:
        self.balance = float(balance)
        self.max_position_notional = max_position_notional
        self.min_position_notional = float(min_position_notional)

    def calculate(
        self,
        *,
        entry: float,
        stop_loss: float,
        risk_per_trade: float,
    ) -> RiskResult:
        if entry <= 0:
            return self._reject("Invalid entry price")

        if stop_loss <= 0:
            return self._reject("Invalid stop loss")

        sl_distance = abs(entry - stop_loss) / entry

        if sl_distance <= 0:
            return self._reject("Invalid SL distance")

        risk_amount = self.balance * risk_per_trade
        position_notional = risk_amount / sl_distance

        if self.max_position_notional is not None:
            position_notional = min(position_notional, self.max_position_notional)

        if position_notional < self.min_position_notional:
            return self._reject("Position notional below minimum")

        quantity = position_notional / entry

        return RiskResult(
            allowed=True,
            risk_amount=risk_amount,
            position_notional=position_notional,
            quantity=quantity,
            reason="OK",
        )

    def validate_signal_risk(
        self,
        *,
        entry: float,
        stop_loss: float,
        max_sl_distance: float,
    ) -> bool:
        if entry <= 0 or stop_loss <= 0:
            return False

        sl_distance = abs(entry - stop_loss) / entry

        return 0 < sl_distance <= max_sl_distance

    def _reject(self, reason: str) -> RiskResult:
        return RiskResult(
            allowed=False,
            risk_amount=0.0,
            position_notional=0.0,
            quantity=0.0,
            reason=reason,
        )