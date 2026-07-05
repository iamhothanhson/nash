from __future__ import annotations

from typing import Any

from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from order_planner.order_planner import OrderPlanner
from risk_manager.risk_manager import RiskManager
from setup_builder.builder import SetupBuilder
from signal_builder.builder import SignalBuilder
from setup_builder.models import SetupType, Side
from executor.executor import Executor
from strategy.liquidity_sweep_reversal.detector import LiquiditySweepDetector
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import BreakoutRetestDetector
from strategy.trend_following.pullback.detector import PullbackDetector
class TradingPipeline:
    def __init__(self, marketplace: Any) -> None:
        self.marketplace = marketplace

        self.detectors = [
            BreakoutDetector.breakout_long,
            BreakoutDetector.breakout_short,
            BreakoutRetestDetector.retest_long,
            BreakoutRetestDetector.retest_short,
            PullbackDetector.pullback_long,
            PullbackDetector.pullback_short,
            LiquiditySweepDetector.sweep_long,
            LiquiditySweepDetector.sweep_short,
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
            except TypeError:
                candidate = None
            if candidate is not None:
                candidates.append(candidate)

        return candidates

    def run_symbol(self, symbol: str) -> Any | None:
        # 1. Marketplace -> OHLCV data
        market_data = self.marketplace.get_market_data(symbol)

        if market_data is None:
            return None

        # 2. Indicators
        indicators = IndicatorBuilder.build(
            market_data,
        )

        # 3. Market State
        market_analyzer = MarketAnalyzer()
        market_state = market_analyzer.build_market_state(
            symbol=symbol,
            data=market_data,
            indicators=indicators,
        )

        # 5. Strategy Detectors -> SetupCandidate
        candidates = self._detect_setups(market_state)

        if not candidates:
            return None

        # 6. Setup Builder -> Setup
        if not candidates:
            return None

        best_candidate = max(candidates, key=lambda c: getattr(c, "confidence", 0.0))
        setup = SetupBuilder.build_from_candidate(
            candidate=best_candidate,
            market_state=market_state,
            score=float(getattr(best_candidate, "confidence", 0.0)),
        )

        if setup is None:
            return None

        # 7. Signal Builder -> Signal
        signal = SignalBuilder.build(
            setup=setup,
            market_state=market_state,
        )

        if signal is None:
            return None

        # 8. Risk Manager -> OrderPlan
        risk = RiskManager.calculate(
            signal=signal
        )

        # 9. Risk Manager -> OrderPlan
        order_plan = OrderPlanner.build_order_plan(
            signal=signal,
            risk=risk,
        )

        if order_plan is None:
            return None

        # 10. Execution
        return Executor.execute(order_plan)