from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable


from backtesting.executor import BacktestExecutor
from backtesting.marketplace import HistoricalMarketplace
from backtesting.portfolio import BacktestPortfolio
from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from setup_builder.builder import SetupBuilder
from signal_builder.builder import SignalBuilder
from risk_manager.risk_manager import RiskManager
from order_planner.order_planner import OrderPlanner
from backtesting.config import LOOKBACK
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import BreakoutRetestDetector
from strategy.trend_following.pullback.detector import PullbackDetector


class BacktestTradingPipeline:
    def __init__(
        self,
        marketplace: HistoricalMarketplace,
        portfolio: BacktestPortfolio,
        executor: BacktestExecutor,
        lookback: int = LOOKBACK,
    ):
        self.lookback = lookback
        self.marketplace = marketplace
        self.portfolio = portfolio
        self.executor = executor
        self.market_analyzer = MarketAnalyzer()

        self.breakout_detector = BreakoutDetector()
        self.retest_detector = BreakoutRetestDetector()
        self.pullback_detector = PullbackDetector()

        self.detectors = [
            self.breakout_detector.detect,
            self.retest_detector.detect,
            self.pullback_detector.detect,
        ]


    def run(
        self,
        symbols: list[str],
        timestamps: Iterable[Any],
    ) -> dict[str, Any]:
        for timestamp in timestamps:
            self._process_timestamp(symbols=symbols, timestamp=timestamp)
        return self.portfolio.get_backtest_result()

    def _process_timestamp(self, symbols: list[str], timestamp: Any) -> None:
        for symbol in symbols:
            candle = self.marketplace.get_candle(symbol=symbol, timestamp=timestamp)
            if candle is None:
                continue
            self.executor.update_positions(
                symbol=symbol,
                candle=candle,
                timestamp=timestamp,
                portfolio=self.portfolio,
            )

        for symbol in symbols:
            self.run_symbol(symbol=symbol, timestamp=timestamp)

        self.portfolio.record_equity(timestamp)

    def run_symbol(self, symbol: str, timestamp: Any) -> Any | None:
        if not self.portfolio.can_open_position(symbol):
            return None

        # Marketplace -> OHLCV data
        market_data = self.marketplace.get_market_data(symbol, up_to=timestamp, lookback=self.lookback)
        if market_data is None:
            return None
        if not self._has_enough_history(market_data):
            return None

        # Indicators
        indicators = IndicatorBuilder.build(market_data)

        # Market State
        market_state = self.market_analyzer.build_market_state(
            symbol=symbol,
            data=market_data,
            indicators=indicators,
        )

        # Strategy Detectors -> SetupCandidate
        candidates = self._detect_setups(market_state)
        if not candidates:
            return None 

        # Setup Builder
        best = self._select_best_candidate(candidates)
        setup = SetupBuilder.build_from_candidate(candidate=best, market_state=market_state)
        if setup is None:
            return None

        # Signal Builder -> TradeSignal
        signal = SignalBuilder.build(setup=setup)
        if signal is None:
            return None

        # Risk Manager
        account_raw = self.portfolio.get_account_state()
        account = SimpleNamespace(
            available_balance=float(account_raw.available_balance),
        )
        risk = RiskManager.calculate(signal=signal, account=account)
        if not risk.allowed:
            return None

        # Order Plan
        order_plan = OrderPlanner.build_order_plan(signal=signal, risk=risk)
        if order_plan is None:
            return None

        # Backtest execution
        current_candle = self.marketplace.get_candle(
            symbol=symbol, timestamp=timestamp,
        )
        if current_candle is None:
            return None

        return self.executor.execute(
            order_plan={
                "symbol": order_plan.symbol,
                "direction": order_plan.direction,
                "entry": order_plan.entry,
                "stop_loss": order_plan.stop_loss,
                "tp1": order_plan.tp1,
                "tp2": order_plan.tp2,
                "tp3": order_plan.tp3,
                "qty": order_plan.qty,
                "risk_amount": order_plan.risk_amount,
                "setup_type": order_plan.setup_type,
                "setup_score": order_plan.setup_score,
            },
            candle=current_candle,
            timestamp=timestamp,
            portfolio=self.portfolio,
        )


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

    @staticmethod
    def _select_best_candidate(candidates: list[Any]) -> Any:
        return max(
            candidates,
            key=lambda c: (
                float(getattr(c, "score", 0.0)),
            ),
        )

    @staticmethod
    def _has_enough_history(
        market_data: dict[str, Any], minimum_bars: int = 60,
    ) -> bool:
        for df in market_data.values():
            if len(df) < minimum_bars:
                return False
        return True
