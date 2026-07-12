from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from risk_manager.config import SCORE_RISK_MULTIPLIERS, SETUP_RISK_MULTIPLIERS
from config import settings


@dataclass(frozen=True, slots=True)
class RiskResult:
    allowed: bool
    risk_amount: float
    position_notional: float
    quantity: float
    reason: str = ""


class RiskManager:
    @classmethod
    def calculate(
        cls,
        signal: Any,
        account: Any,
    ) -> RiskResult:
        entry = float(getattr(signal, "entry", 0.0))
        stop_loss = float(getattr(signal, "stop_loss", 0.0))

        if entry <= 0:
            return cls._reject("Invalid entry price")
        if stop_loss <= 0:
            return cls._reject("Invalid stop loss")

        sl_distance = abs(entry - stop_loss) / entry
        if sl_distance <= 0:
            return cls._reject("Invalid SL distance")

        available_balance = account.available_balance
        risk_per_trade = float(getattr(signal, "signal_risk_per_trade", 0.0))
        setup_type = str(getattr(signal, "setup_type", "")).strip()
        score = int(getattr(signal, "setup_score", 0))
        
        mult = cls.compute_risk_multiplier(setup_type, score)
        risk_amount = available_balance * risk_per_trade * mult

        position_notional = risk_amount / sl_distance

        max_notional = getattr(settings, "MAX_POSITION_NOTIONAL", None)
        if max_notional is not None and position_notional > float(max_notional):
            position_notional = float(max_notional)

        min_notional = float(getattr(settings, "MIN_POSITION_NOTIONAL", 25))
        if position_notional < min_notional:
            return cls._reject(
                f"Position notional {position_notional:.2f} below minimum {min_notional:.2f}"
            )

        quantity = position_notional / entry

        return RiskResult(
            allowed=True,
            risk_amount=risk_amount,
            position_notional=position_notional,
            quantity=quantity,
            reason="OK",
        )

    @classmethod
    def validate_signal_risk(
        cls,
        *,
        entry: float,
        stop_loss: float,
        max_sl_distance: float,
    ) -> bool:
        if entry <= 0 or stop_loss <= 0:
            return False
        sl_distance = abs(entry - stop_loss) / entry
        return 0 < sl_distance <= max_sl_distance

    @staticmethod
    def compute_risk_multiplier(
        setup_type: str,
        score: int,
    ) -> float:
        setup_mult = SETUP_RISK_MULTIPLIERS.get(setup_type, 1.0)
        score_mult = next(
            (v for k, v in sorted(SCORE_RISK_MULTIPLIERS.items(), reverse=True) if score >= k),
            1.0,
        )
        return setup_mult * score_mult

    @classmethod
    def _reject(cls, reason: str) -> RiskResult:
        return RiskResult(
            allowed=False,
            risk_amount=0.0,
            position_notional=0.0,
            quantity=0.0,
            reason=reason,
        )