from __future__ import annotations

from typing import Any

from executor.executor import Executor
from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from exchange.account_service import AccountService
from order_planner.order_planner import OrderPlanner
from risk_manager.risk_manager import RiskManager
from setup_builder.builder import SetupBuilder
from signal_builder.builder import SignalBuilder
from config.settings import ENABLE_LIQUIDITY_SWEEP_REVERSAL
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import BreakoutRetestDetector
from strategy.trend_following.pullback.detector import PullbackDetector
class TradingPipeline:
    def __init__(self, marketplace: Any, account_service: AccountService | None = None) -> None:
        self.marketplace = marketplace
        self.account_service = account_service or AccountService()

        self.breakout_detector = BreakoutDetector()
        self.retest_detector = BreakoutRetestDetector()
        self.pullback_detector = PullbackDetector()

        self.detectors = [
            self.breakout_detector.detect,
            self.retest_detector.detect,
            self.pullback_detector.detect,
        ]

    def run(self, symbols: list[str]) -> dict[str, Any]:
        results: dict[str, Any] = {}

        for symbol in symbols:
            result = self.run_symbol(symbol)

            if result is not None:
                results[symbol] = result

        return results

    def _detect_setups(self, market_state: Any) -> list[Any]:
        candidates: list[Any] = []

        for detector in self.detectors:
            try:
                candidate = detector(market_state)
            except (TypeError, ValueError, KeyError):
                candidate = None
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def run_symbol(self, symbol: str) -> Any | None:
        # Marketplace -> OHLCV data
        market_data = self.marketplace.get_market_data(symbol)

        if market_data is None:
            return None

        # Indicators
        indicators = IndicatorBuilder.build(
            market_data,
        )

        # Market State
        market_analyzer = MarketAnalyzer()
        market_state = market_analyzer.build_market_state(
            symbol=symbol,
            data=market_data,
            indicators=indicators,
        )

        # Strategy Detectors -> SetupCandidate
        candidates = self._detect_setups(market_state)

        # Setup Builder -> Setup
        if not candidates:
            return None

        best_candidate = self._select_best_candidate(candidates)
        setup = SetupBuilder.build_from_candidate(
            candidate=best_candidate,
            market_state=market_state,
        )

        if setup is None:
            return None

        # Signal Builder -> Signal
        signal = SignalBuilder.build(setup=setup)

        if signal is None:
            return None

        # Risk Manager
        account = self.account_service.get_account_state()
        risk = RiskManager.calculate(
            signal=signal,
            account=account
        )
        if not risk.allowed:
            return None

        # OrderPlan
        order_plan = OrderPlanner.build_order_plan(
            signal=signal,
            risk=risk,
        )

        if order_plan is None:
            return None

        # Execution
        return Executor.execute(order_plan)

    @staticmethod
    def _select_best_candidate(candidates: list[Any]) -> Any:
        return max(
            candidates,
            key=lambda c: float(getattr(c, "score", 0.0)),
        )