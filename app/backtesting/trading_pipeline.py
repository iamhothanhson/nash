from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Iterable

import pandas as pd

from backtesting.executor import BacktestExecutor
from backtesting.marketplace import HistoricalMarketplace
from backtesting.portfolio import BacktestPortfolio
from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from setup_builder.builder import SetupBuilder
from signal_builder.builder import SignalBuilder
from risk_manager.risk_manager import RiskManager
from order_planner.order_planner import OrderPlanner
from config.settings import ENABLE_LIQUIDITY_SWEEP_REVERSAL
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import BreakoutRetestDetector
from strategy.trend_following.pullback.detector import PullbackDetector


LOOKBACK = 200


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
            self.breakout_detector.breakout_long_candidate,
            self.breakout_detector.breakout_short_candidate,
            self.retest_detector.detect_long,
            self.retest_detector.detect_short,
            self.pullback_detector.detect_long,
            self.pullback_detector.detect_short,
        ]

        if ENABLE_LIQUIDITY_SWEEP_REVERSAL:
            from strategy.liquidity_sweep_reversal.detector import LiquiditySweepDetector

            sd = LiquiditySweepDetector()
            self.detectors.extend([sd.detect_long, sd.detect_short])

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
        market_data = self._market_data_since(symbol, up_to=timestamp)
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
        setup = SetupBuilder.build(candidate=best, market_state=market_state)
        if setup is None or setup.grade == "Skip":
            return None

        # Signal Builder -> TradeSignal
        entry = float(
            market_data.get("15m", list(market_data.values())[0]).iloc[-1]["close"]
        )
        signal = SignalBuilder.build(setup=setup, entry=entry)
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

    def _market_data_since(
        self, symbol: str, up_to: Any,
    ) -> dict[str, pd.DataFrame] | None:
        symbol_data = self.marketplace.data.get(symbol)
        if symbol_data is None:
            return None
        result: dict[str, pd.DataFrame] = {}
        for tf, df in symbol_data.items():
            idx = df.index.get_loc(up_to) if up_to in df.index else -1
            if idx < 0:
                return None
            start = max(0, idx - self.lookback + 1)
            result[tf] = df.iloc[start: idx + 1]
        return result

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
                float(getattr(c, "confidence", 0.0)),
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
