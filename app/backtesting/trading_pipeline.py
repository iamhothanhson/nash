from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable


from backtesting.executor import BacktestExecutor
from backtesting.marketplace import HistoricalMarketplace
from backtesting.position import BacktestPositionManager
from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from setup_builder.builder import SetupBuilder
from signal_builder.builder import SignalBuilder
from risk_manager.risk_manager import RiskManager
from order_planner.order_planner import OrderPlanner
from backtesting.config import INDICATOR_WARMUP_BARS
from backtesting.utils import has_enough_history
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import BreakoutRetestDetector
from strategy.trend_following.pullback.detector import PullbackDetector


class BacktestTradingPipeline:
    def __init__(
        self,
        marketplace: HistoricalMarketplace,
        position_manager: BacktestPositionManager,
        executor: BacktestExecutor,
        lookback: int = INDICATOR_WARMUP_BARS,
    ):
        self.lookback = lookback
        self.marketplace = marketplace
        self.position_manager = position_manager
        self.executor = executor
        self.market_analyzer = MarketAnalyzer()

        self.breakout_detector = BreakoutDetector()

        self.detectors = [
            self.breakout_detector.detect
        ]


    def run(
        self,
        symbols: list[str],
        timestamps: Iterable[Any],
    ) -> dict[str, Any]:
        for timestamp in timestamps:
            self._process_timestamp(symbols=symbols, timestamp=timestamp)
        return self.position_manager.get_backtest_result()

    def _process_timestamp(self, symbols: list[str], timestamp: Any) -> None:
        for symbol in symbols:
            candle = self.marketplace.get_candle(symbol=symbol, timestamp=timestamp)
            if candle is None:
                continue
            self.position_manager.update_positions(
                symbol=symbol,
                candle=candle,
                timestamp=timestamp,
            )

        for symbol in symbols:
            self.run_symbol(symbol=symbol, timestamp=timestamp)

        self.position_manager.record_equity(timestamp)

    def run_symbol(self, symbol: str, timestamp: Any) -> Any | None:
        if not self.position_manager.can_open_position(symbol):
            return None

        # Marketplace -> OHLCV data
        market_data = self.marketplace.get_market_data(symbol, up_to=timestamp, lookback=self.lookback)
        if market_data is None:
            return None
        if not has_enough_history(market_data):
            return None

        # Indicators
        indicators = IndicatorBuilder.build(market_data)

        # Market State
        ts_ms = int(timestamp.timestamp() * 1000) if hasattr(timestamp, "timestamp") else int(timestamp)
        market_state = self.market_analyzer.build_market_state(
            symbol=symbol,
            data=market_data,
            indicators=indicators,
            timestamp=ts_ms,
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
        account_raw = self.position_manager.get_account_state()
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

        return self.executor.execute(order_plan, timestamp=timestamp)


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
