from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from backtesting.executor import BacktestExecutor
from backtesting.marketplace import HistoricalMarketplace
from backtesting.portfolio import BacktestPortfolio
from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from setup_builder.builder import SetupBuilder
from config.settings import ENABLE_LIQUIDITY_SWEEP_REVERSAL
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import (
    BreakoutRetestDetector,
)
from strategy.trend_following.pullback.detector import PullbackDetector


HISTORY_DIR = Path(__file__).resolve().parent / "history_data"
LOOKBACK = 200


def load_history_marketplace() -> HistoricalMarketplace:
    data: dict[str, dict[str, pd.DataFrame]] = {}

    for csv_path in sorted(HISTORY_DIR.glob("*.csv")):
        parts = csv_path.stem.split("_")
        symbol = parts[0] if parts[0].endswith("USDT") else parts[0] + "USDT"
        interval = parts[1] if len(parts) > 1 else "15m"
        interval_map = {"5m": "5m", "15m": "15m", "1h": "1h"}
        interval = interval_map.get(interval, "15m")

        raw = pd.read_csv(csv_path)
        if "time" in raw.columns:
            raw["datetime"] = pd.to_datetime(raw["time"], unit="ms")
        elif "open_time" in raw.columns:
            raw["datetime"] = pd.to_datetime(raw["open_time"], unit="ms")
        else:
            raw["datetime"] = pd.date_range(
                end=datetime.now(), periods=len(raw), freq=interval.replace("m", "min")
            )

        raw.set_index("datetime", inplace=True)
        raw.index.name = "datetime"
        for col in ["open", "high", "low", "close", "volume"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")
        df = raw[["open", "high", "low", "close", "volume"]]

        data.setdefault(symbol, {})[interval] = df

    return HistoricalMarketplace(data)


class BacktestTradingPipeline:
    def __init__(
        self,
        marketplace: HistoricalMarketplace,
        portfolio: BacktestPortfolio,
        executor: BacktestExecutor,
        lookback: int = 200,
    ) -> None:
        self.lookback = lookback
        self.marketplace = marketplace
        self.portfolio = portfolio
        self.executor = executor
        self.market_analyzer = MarketAnalyzer()
        self.breakout_detector = BreakoutDetector()
        self.retest_detector = BreakoutRetestDetector()
        self.pullback_detector = PullbackDetector()
        self.sweep_detector = None

        self.detectors = [
            self.breakout_detector.breakout_long_candidate,
            self.breakout_detector.breakout_short_candidate,
            self.retest_detector.detect_long,
            self.retest_detector.detect_short,
            self.pullback_detector.detect_long,
            self.pullback_detector.detect_short,
        ]

        if ENABLE_LIQUIDITY_SWEEP_REVERSAL:
            from strategy.liquidity_sweep_reversal.detector import (
                LiquiditySweepDetector,
            )

            sd = LiquiditySweepDetector()
            self.sweep_detector = sd
            self.detectors.extend([sd.detect_long, sd.detect_short])

        # Pre-compute row lookups per symbol/timeframe for fast slicing
        self._index_map: dict[str, dict[str, pd.Index]] = {}
        for sym, tfs in marketplace.data.items():
            self._index_map[sym] = {tf: df.index for tf, df in tfs.items()}

    def _market_data_since(
        self, symbol: str, up_to: Any
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
            result[tf] = df.iloc[start:idx + 1]
        return result

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

        market_data = self._market_data_since(symbol, up_to=timestamp)
        if market_data is None:
            return None
        if not self._has_enough_history(market_data):
            return None

        indicators = IndicatorBuilder.build(market_data)

        market_state = self.market_analyzer.build_market_state(
            symbol=symbol, data=market_data, indicators=indicators,
        )

        candidates = self._detect_setups(market_state)
        if not candidates:
            return None

        best = self._select_best_candidate(candidates)

        setup = SetupBuilder.build(candidate=best, market_state=market_state)
        if setup is None or setup.grade == "Skip":
            return None

        entry = float(
            market_data.get("15m", list(market_data.values())[0]).iloc[-1]["close"]
        )
        signal = self._build_signal(setup, entry, market_state)
        if signal is None:
            return None

        account = self.portfolio.get_account_state()
        risk = self._calculate_risk(signal, account)
        if risk is None:
            return None

        current_candle = self.marketplace.get_candle(
            symbol=symbol, timestamp=timestamp,
        )
        if current_candle is None:
            return None

        order_plan = {
            "symbol": symbol,
            "direction": signal["direction"],
            "entry": signal["entry"],
            "stop_loss": signal["stop_loss"],
            "tp1": signal["tp1"],
            "tp2": signal["tp2"],
            "tp3": signal.get("tp3", 0.0),
            "qty": risk["quantity"],
            "risk_amount": risk["risk_amount"],
            "setup_type": signal.get("setup_type"),
            "setup_score": setup.score,
        }

        return self.executor.execute(
            order_plan=order_plan,
            candle=current_candle,
            timestamp=timestamp,
            portfolio=self.portfolio,
        )

    def _build_signal(self, setup, entry: float, market_state) -> dict | None:
        cfg = BREAKOUT_LONG if setup.side.upper() == "LONG" else BREAKOUT_SHORT
        direction = setup.side.upper()
        atr_pct = float(
            getattr(market_state, "indicators", {}).get("atr_percent", 0.0)
        )
        anchor = float(getattr(setup, "anchor", entry))
        atr_v = atr_pct * entry

        stop_atr_mult = 1.5
        buf = atr_v * stop_atr_mult

        if direction == "LONG":
            sl = anchor - buf
            dist = (entry - sl) / entry
        else:
            sl = anchor + buf
            dist = (sl - entry) / entry

        min_sl = cfg.get("min_sl_distance", 0.003)
        if dist < min_sl:
            if direction == "LONG":
                sl = entry * (1.0 - min_sl)
            else:
                sl = entry * (1.0 + min_sl)
            dist = min_sl

        if dist <= 0 or dist > 0.1:
            return None

        tp1_r = 1.0
        tp2_r = 1.5
        tp3_r = 2.0
        if direction == "LONG":
            tp1 = entry + dist * tp1_r * entry
            tp2 = entry + dist * tp2_r * entry
            tp3 = entry + dist * tp3_r * entry
        else:
            tp1 = entry - dist * tp1_r * entry
            tp2 = entry - dist * tp2_r * entry
            tp3 = entry - dist * tp3_r * entry

        return {
            "direction": direction,
            "entry": entry,
            "stop_loss": sl,
            "tp1": tp1,
            "tp2": tp2,
            "tp3": tp3,
            "r_multiple": dist,
            "setup_grade": setup.grade,
            "setup_type": setup.setup_type,
        }

    def _calculate_risk(self, signal: dict, account_state) -> dict | None:
        entry = signal["entry"]
        sl = signal["stop_loss"]
        sl_distance = abs(entry - sl) / entry
        if sl_distance <= 0:
            return None

        available = float(getattr(account_state, "available_balance", 0))
        if available <= 0:
            return None

        risk_amount = available * 0.01
        position_notional = risk_amount / sl_distance
        quantity = position_notional / entry

        return {
            "allowed": True,
            "risk_amount": risk_amount,
            "position_notional": position_notional,
            "quantity": quantity,
        }

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
        market_data: dict[str, Any], minimum_bars: int = 60
    ) -> bool:
        for df in market_data.values():
            if len(df) < minimum_bars:
                return False
        return True


if __name__ == "__main__":
    mp = load_history_marketplace()
    portfolio = BacktestPortfolio(initial_balance=10000.0)
    executor = BacktestExecutor()

    symbols = ["TAOUSDT"]
    timestamps = mp.data["TAOUSDT"]["15m"].index[200:]

    pipeline = BacktestTradingPipeline(marketplace=mp, portfolio=portfolio, executor=executor)
    result = pipeline.run(symbols=symbols, timestamps=timestamps)

    trades = result["trades"]
    equity = result["equity_curve"]

    print(f"\n  Total Trades: {len(trades)}")
    print(f"  Final Balance: {result['final_balance']:.2f}")
    winners = [t for t in trades if t.net_pnl > 0]
    losers = [t for t in trades if t.net_pnl <= 0]
    print(f"  Win Rate: {len(winners) / max(len(trades), 1) * 100:.1f}%")
    if losers:
        pf = sum(t.net_pnl for t in winners) / abs(sum(t.net_pnl for t in losers)) if losers else float("inf")
        print(f"  Profit Factor: {pf:.2f}")
    if equity:
        peak = max(e.equity for e in equity)
        trough = min(e.equity for e in equity)
        dd = (peak - trough) / peak * 100 if peak else 0
        print(f"  Max Drawdown: {dd:.2f}%")
    print(f"  Trades count: {len(trades)}")
    for t in trades:
        print(f"    {t.direction:5s} entry={t.entry_price:.2f} exit={t.exit_price:.2f} pnl={t.net_pnl:.2f} reason={t.exit_reason}")
    print()
