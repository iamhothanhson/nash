"""
pre_trade_checker.py

Centralized validation before opening a new position.

Responsibilities:
- Validate account constraints
- Validate portfolio constraints
- Validate risk constraints
- Validate market conditions
- Return rejection reason for logging
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class RejectReason(str, Enum):
    NONE = "NONE"

    # Portfolio
    MAX_POSITIONS = "MAX_POSITIONS"
    SYMBOL_ALREADY_OPEN = "SYMBOL_ALREADY_OPEN"
    MAX_SYMBOL_EXPOSURE = "MAX_SYMBOL_EXPOSURE"
    MAX_TOTAL_EXPOSURE = "MAX_TOTAL_EXPOSURE"

    # Risk
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MAX_DRAWDOWN = "MAX_DRAWDOWN"
    COOLDOWN = "COOLDOWN"

    # Account
    INSUFFICIENT_MARGIN = "INSUFFICIENT_MARGIN"

    # Market
    SPREAD_TOO_WIDE = "SPREAD_TOO_WIDE"
    LOW_LIQUIDITY = "LOW_LIQUIDITY"
    HIGH_FUNDING = "HIGH_FUNDING"

    # Signal
    EXPIRED_SIGNAL = "EXPIRED_SIGNAL"

    UNKNOWN = "UNKNOWN"


@dataclass
class PreTradeResult:
    allowed: bool
    reason: RejectReason = RejectReason.NONE
    message: str = ""


class PreTradeChecker:

    def __init__(
        self,
        risk_manager,
        portfolio,
        account,
        market_service,
        config,
    ):
        self.risk_manager = risk_manager
        self.portfolio = portfolio
        self.account = account
        self.market = market_service
        self.config = config

    def can_open_position(
        self,
        signal,
    ) -> PreTradeResult:

        checks = [
            self._check_max_positions,
            self._check_existing_position,
            self._check_total_exposure,
            self._check_daily_loss,
            self._check_margin,
            self._check_spread,
            self._check_liquidity,
            self._check_signal_age,
        ]

        for check in checks:
            result = check(signal)

            if not result.allowed:
                return result

        return PreTradeResult(True)

    # Portfolio
    def _check_max_positions(self, signal):

        if self.portfolio.position_count >= self.config.MAX_POSITIONS:
            return PreTradeResult(
                False,
                RejectReason.MAX_POSITIONS,
                "Maximum number of positions reached.",
            )

        return PreTradeResult(True)

    def _check_existing_position(self, signal):

        if self.portfolio.has_position(signal.symbol):
            return PreTradeResult(
                False,
                RejectReason.SYMBOL_ALREADY_OPEN,
                f"Position already exists for {signal.symbol}.",
            )

        return PreTradeResult(True)

    def _check_total_exposure(self, signal):

        if self.portfolio.total_exposure >= self.config.MAX_TOTAL_EXPOSURE:
            return PreTradeResult(
                False,
                RejectReason.MAX_TOTAL_EXPOSURE,
                "Portfolio exposure exceeded.",
            )

        return PreTradeResult(True)

    # Risk
    def _check_daily_loss(self, signal):

        if self.risk_manager.daily_loss_limit_hit():
            return PreTradeResult(
                False,
                RejectReason.DAILY_LOSS_LIMIT,
                "Daily loss limit reached.",
            )

        return PreTradeResult(True)

    # Account
    def _check_margin(self, signal):

        if not self.account.has_available_margin():
            return PreTradeResult(
                False,
                RejectReason.INSUFFICIENT_MARGIN,
                "Insufficient margin.",
            )

        return PreTradeResult(True)