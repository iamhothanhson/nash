from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from typing import Any

from core.enums import RejectReason
from risk_manager.config import GRADE_RISK_MULTIPLIERS, REGIME_RISK_MULTIPLIERS, SETUP_RISK_MULTIPLIERS
from app.core import settings
from app.core.config import SETUP_CONFIGS


@dataclass(frozen=True, slots=True)
class RiskResult:
    allowed: bool
    risk_per_trade: float
    risk_amount: float
    position_notional: float
    quantity: float
    risk_multiplier: float = 1.0
    reason: str = ""


class RiskManager:
    @staticmethod
    def validate_sl_distance(
        sl_distance: float,
        setup_type: str,
    ) -> tuple[bool, str]:
        if sl_distance <= 0:
            return False, "Invalid SL distance"

        config = SETUP_CONFIGS.get(setup_type)
        if config is None:
            return True, ""

        min_sl = config.get("min_sl_distance")
        max_sl = config.get("max_sl_distance")

        if min_sl is not None and sl_distance < min_sl:
            return False, f"SL distance {sl_distance:.4f} below minimum {min_sl:.4f}"
        if max_sl is not None and sl_distance > max_sl:
            return False, f"SL distance {sl_distance:.4f} above maximum {max_sl:.4f}"

        return True, ""

    @classmethod
    def calculate(
        cls,
        signal: Any,
        account: Any,
        reject_stats: Any = None,
        pipeline_stats: Any = None,
    ) -> RiskResult:
        entry = float(getattr(signal, "entry", 0.0))
        stop_loss = float(getattr(signal, "stop_loss", 0.0))

        if entry <= 0:
            return cls._reject("Invalid entry price", reject_stats=reject_stats)
        if stop_loss <= 0:
            return cls._reject("Invalid stop loss", reject_stats=reject_stats)

        sl_distance = getattr(signal, "sl_distance", 0.0)
        setup_type = str(getattr(signal, "setup_type", "")).strip()

        valid, reason = cls.validate_sl_distance(sl_distance, setup_type)
        if not valid:
            return cls._reject(reason, reject_stats=reject_stats)

        available_balance = account.available_balance
        
        base_risk_per_trade = float(settings.RISK_PER_TRADE)
        setup_grade = str(getattr(signal, "setup_grade", "")).strip().upper()
        regime = str(getattr(signal, "market_state.regime", "")).strip()
        
        mult = cls.compute_risk_multiplier(setup_type, setup_grade, regime)
        risk_per_trade = base_risk_per_trade * mult
        risk_amount = available_balance * risk_per_trade

        position_notional = risk_amount / sl_distance

        max_notional = getattr(settings, "MAX_POSITION_NOTIONAL", None)
        if max_notional is not None and position_notional > float(max_notional):
            position_notional = float(max_notional)

        min_notional = float(getattr(settings, "MIN_POSITION_NOTIONAL", 25))
        if position_notional < min_notional:
            return cls._reject(
                f"Position notional {position_notional:.2f} below minimum {min_notional:.2f}",
                reject_stats=reject_stats,
            )

        quantity = position_notional / entry

        if pipeline_stats:
            pipeline_stats.risk_allowed += 1

        return RiskResult(
            allowed=True,
            risk_amount=risk_amount,
            position_notional=position_notional,
            quantity=quantity,
            risk_per_trade=risk_per_trade,
            risk_multiplier=mult,
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
        setup_grade: str,
        regime: str
    ) -> float:
        setup_mult = SETUP_RISK_MULTIPLIERS.get(setup_type, 1.0)
        grade_mult = GRADE_RISK_MULTIPLIERS.get(setup_grade, 1.0)
        regime_mult = REGIME_RISK_MULTIPLIERS.get(regime, 1.0)
        return setup_mult * grade_mult * regime_mult

    @classmethod
    def _reject(cls, reason: str, reject_stats: Any = None) -> RiskResult:
        if reject_stats:
            reject_stats.reject(RejectReason.RISK)
        return RiskResult(
            allowed=False,
            risk_per_trade=0.0,
            risk_amount=0.0,
            position_notional=0.0,
            quantity=0.0,
            risk_multiplier=0.0,
            reason=reason,
        )