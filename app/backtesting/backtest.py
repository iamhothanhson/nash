from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtrader as bt
import pandas as pd
from config.settings import INITIAL_CAPITAL

from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.market_analyzer import MarketAnalyzer
from market_analyzer.market_state import (
    MarketState,
)
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT
from strategy.trend_following.breakout.detector import BreakoutDetector
from strategy.trend_following.breakout_retest.detector import BreakoutRetestDetector
from strategy.trend_following.pullback.detector import PullbackDetector
from setup_builder.builder import SetupBuilder


HISTORY_DIR = Path(__file__).resolve().parent / "history_data"

_STRATEGY_LABELS = {
    "breakout": "Breakout",
    "breakout_retest": "Breakout Retest",
    "pullback": "Pullback",
    "liquidity_sweep": "Liquidity Reversal",
}


def load_bt_data(
    symbol: str,
    interval: str = "15m",
    limit: int = 500,
) -> pd.DataFrame:
    csv_path = HISTORY_DIR / f"{symbol}_{interval}.csv"
    if csv_path.exists():
        raw = pd.read_csv(csv_path)
    else:
        import requests
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        resp = requests.get(
            "https://fapi.binance.com/fapi/v1/klines",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()
        candles = resp.json()
        if not candles:
            raise ValueError(f"No data for {symbol} {interval}")
        raw = pd.DataFrame(
            candles,
            columns=[
                "open_time", "open", "high", "low", "close", "volume",
                "close_time", "quote_asset_volume", "number_of_trades",
                "taker_buy_base_volume", "taker_buy_quote_volume", "ignore",
            ],
        )
        for col in ["open", "high", "low", "close", "volume"]:
            raw[col] = pd.to_numeric(raw[col], errors="coerce")

    if "time" in raw.columns:
        raw["datetime"] = pd.to_datetime(raw["time"], unit="ms")
        raw.drop(columns=["time"], inplace=True)
    elif "open_time" in raw.columns:
        raw["datetime"] = pd.to_datetime(raw["open_time"], unit="ms")
        raw.drop(columns=["open_time"], inplace=True)
    else:
        raw["datetime"] = pd.date_range(
            end=datetime.now(), periods=len(raw),
            freq=interval.replace("m", "min"),
        )

    raw.set_index("datetime", inplace=True)
    raw.index.name = "datetime"
    return raw[["open", "high", "low", "close", "volume"]]


class MultiStrategyBT(bt.Strategy):
    params = (
        ("risk_per_trade", 0.01),
        ("sl_atr_mult", 1.5),
        ("min_history", 60),
        ("max_hold_bars", 24),
    )

    def __init__(self):
        self.breakout_detector = BreakoutDetector()
        self.retest_detector = BreakoutRetestDetector()
        self.pullback_detector = PullbackDetector()
        self.sweep_detector = None
        try:
            from strategy.liquidity_sweep_reversal.detector import LiquiditySweepDetector
            self.sweep_detector = LiquiditySweepDetector()
        except Exception:
            pass

        self.trade_log: list[dict] = []
        self._entry_bar: int | None = None
        self._current_tradeinfo: dict = {}

    def _detect(self, ms) -> Any | None:
        detectors = [
            self.breakout_detector.breakout_long_candidate,
            self.breakout_detector.breakout_short_candidate,
            self.retest_detector.detect_long,
            self.retest_detector.detect_short,
            self.pullback_detector.detect_long,
            self.pullback_detector.detect_short,
        ]
        if self.sweep_detector is not None:
            detectors.extend([
                self.sweep_detector.detect_long,
                self.sweep_detector.detect_short,
            ])

        best = None
        for detect in detectors:
            try:
                c = detect(ms)
            except Exception:
                c = None
            if c is not None and (best is None or getattr(c, "confidence", 0.0) > getattr(best, "confidence", 0.0)):
                best = c
        return best

    def _build_ohlcv(self, bars: int = 60) -> pd.DataFrame | None:
        n = min(bars, len(self.data))
        if n < 60:
            return None
        return pd.DataFrame(
            {
                "open": self.data.open.get(size=n),
                "high": self.data.high.get(size=n),
                "low": self.data.low.get(size=n),
                "close": self.data.close.get(size=n),
                "volume": self.data.volume.get(size=n),
            },
            index=pd.DatetimeIndex(self.data.datetime.array[-n:]),
        )

    def _build_market_state(self) -> MarketState | None:
        df = self._build_ohlcv()
        if df is None:
            return None

        symbol = self.data._name or ""
        indicators = IndicatorBuilder.build(market_data={"15m": df})
        analyzer = MarketAnalyzer()
        return analyzer.build_market_state(
            symbol=symbol,
            data={"15m": df},
            indicators=indicators,
        )

    def notify_trade(self, trade):
        if not trade.isclosed:
            return
        pnl = trade.pnlcomm
        size = self._current_tradeinfo.get("_size", trade.size)
        if not size:
            return
        entry_price = trade.price
        exit_price = entry_price + pnl / size
        margin = size * entry_price

        info = self._current_tradeinfo
        self.trade_log.append({
            "strategy": info.get("strategy", "unknown"),
            "direction": info.get("direction", "LONG"),
            "grade": info.get("grade", "Skip"),
            "entry": entry_price,
            "exit": exit_price,
            "size": size,
            "margin": margin,
            "pnl": pnl,
            "roi_pct": (pnl / margin * 100) if margin > 0 else 0.0,
            "bars": trade.barlen,
        })

    def _manage_position(self, ms: MarketState):
        if not self.position:
            return

        if self._entry_bar is not None and len(self.data) - self._entry_bar >= self.p.max_hold_bars:
            self.close()
            return

    def next(self):
        if len(self.data) < self.p.min_history:
            return

        ms = self._build_market_state()
        if ms is None or ms.features is None:
            return

        if self.position:
            self._manage_position(ms)
            return

        best = self._detect(ms)
        if best is None:
            return

        setup = SetupBuilder.build(
            candidate=best,
            market_state=ms,
        )
        if setup is None or setup.grade == "Skip":
            return

        cfg = BREAKOUT_LONG if best.direction == "LONG" else BREAKOUT_SHORT
        close = self.data.close[0]
        atr_pct = float(ms.indicators.get("atr_percent", 0.0))

        sl_distance = max(
            cfg.get("min_sl_distance", 0.003),
            atr_pct * self.p.sl_atr_mult,
        )
        sl_price = close - sl_distance if best.direction == "LONG" else close + sl_distance

        value_per_risk = self.broker.getvalue() * self.p.risk_per_trade
        size = value_per_risk / close

        self._current_tradeinfo = {
            "strategy": best.setup_type,
            "direction": best.direction,
            "grade": setup.grade,
            "_size": size,
        }
        if best.direction == "LONG":
            o = self.buy(size=size, sl=sl_price)
        else:
            o = self.sell(size=size, sl=sl_price)
        if o:
            self._entry_bar = len(self.data)


def run_backtest(
    symbol: str = "TAOUSDT",
    interval: str = "15m",
    since: str | None = None,
    until: str | None = None,
    cash: float = 10000.0,
    days: int | None = None,
) -> None:
    start_time = time.time()
    df = load_bt_data(symbol, interval)

    if days is not None:
        end = pd.Timestamp(until) if until else df.index[-1]
        since = (end - timedelta(days=days)).strftime("%Y-%m-%d")
        until = end.strftime("%Y-%m-%d")
    else:
        since = since or "2026-03-01"
        until = until or "2026-05-10"

    df = df[since:until]
    if df.empty:
        print(f"No data for {symbol} {interval} in [{since}, {until}]")
        return

    data = bt.feeds.PandasData(dataname=df)

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.adddata(data, name=symbol)
    cerebro.addstrategy(MultiStrategyBT)
    cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0004)

    results = cerebro.run()
    strat = results[0]
    elapsed = time.time() - start_time

    ta = strat.analyzers.trades.get_analysis()
    dd = strat.analyzers.drawdown.get_analysis()
    trade_log = strat.trade_log

    final_value = cerebro.broker.getvalue()
    net_profit = final_value - cash
    roi_pct = (net_profit / cash) * 100

    total_trades = ta.get("total", {}).get("closed", 0)
    won = ta.get("won", {}).get("total", 0)
    lost = ta.get("lost", {}).get("total", 0)
    won_pnl = ta.get("won", {}).get("pnl", {}).get("total", 0)
    lost_pnl = abs(ta.get("lost", {}).get("pnl", {}).get("total", 0))
    profit_factor = won_pnl / lost_pnl if lost_pnl else float("inf")
    win_rate = (won / total_trades * 100) if total_trades else 0.0
    max_dd = dd.get("max", {}).get("drawdown", 0.0)

    trading_days = max((df.index[-1] - df.index[0]).days, 1)
    trades_per_day = total_trades / trading_days

    grade_counts = {"A+": 0, "A": 0}
    for t in trade_log:
        g = t.get("grade", "Skip")
        if g == "A+" or g == "A":
            grade_counts[g] += 1

    strat_groups: dict[str, list[dict]] = {}
    for t in trade_log:
        key = t["strategy"]
        strat_groups.setdefault(key, []).append(t)

    print()
    print(f"  MODE: backtest | DATA SOURCE: history")
    print(f"  Coins: {symbol.replace('USDT', '').upper()}")
    print(f"  Initial Balance: {cash:.2f}")
    print(f"  Net Profit: {net_profit:+.2f}")
    print(f"  ROI: {roi_pct:+.2f}%")
    print(f"  Total Trades: {total_trades}")
    print(f"  Trades per Day: {trades_per_day:.2f}")
    print(f"  Win Rate: {win_rate:.2f}%")
    print(f"  Profit Factor: {profit_factor:.2f}")
    print(f"  Max Drawdown: {max_dd:.2f}%")
    print(f"  A+ Trades: {grade_counts['A+']}")
    print(f"  A Trades: {grade_counts['A']}")

    trend_sub = {"pullback": [], "breakout": [], "breakout_retest": []}
    for key, trades in sorted(strat_groups.items()):
        label = _STRATEGY_LABELS.get(key, key)
        count = len(trades)
        avg_margin = sum(t["margin"] for t in trades) / count
        total_pnl = sum(t["pnl"] for t in trades)
        group_roi = (total_pnl / cash) * 100
        avg_margin_val = avg_margin

        if key in trend_sub:
            trend_sub[key] = trades

    lsr_trades = strat_groups.get("liquidity_sweep", [])
    if lsr_trades:
        c = len(lsr_trades)
        am = sum(t["margin"] for t in lsr_trades) / c
        tp = sum(t["pnl"] for t in lsr_trades)
        r = (tp / cash) * 100
        print(f"  Liquidity Reversal: {c} trades, Avg Margin: {am:.2f} USDT, ROI: {r:+.2f}%, Net Profit: {tp:+.2f} USDT")

    tf_trades = trend_sub["pullback"] + trend_sub["breakout"] + trend_sub["breakout_retest"]
    if tf_trades:
        print(f"  Trend Following: {len(tf_trades)} trades:")
        for skey, slabel in [("pullback", "Pullback"), ("breakout", "Breakout"), ("breakout_retest", "Breakout Retest")]:
            st = trend_sub[skey]
            if not st:
                continue
            c = len(st)
            am = sum(t["margin"] for t in st) / c
            tp = sum(t["pnl"] for t in st)
            r = (tp / cash) * 100
            print(f"    - {slabel}: {c} trades, Avg Margin: {am:.2f} USDT, ROI: {r:+.2f}%, Net Profit: {tp:+.2f} USDT")

    print(f"  Running Time: {int(elapsed // 60)}:{int(elapsed % 60):02d} s")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run multi-strategy backtest with backtrader")
    parser.add_argument("--symbol", default="TAOUSDT", help="Trading pair (default: TAOUSDT)")
    parser.add_argument("--interval", default="15m", choices=["5m", "15m", "1h"], help="Chart interval (default: 15m)")
    parser.add_argument("--days", type=int, default=None, help="Number of days to backtest (overrides --since)")
    parser.add_argument("--since", default=None, help="Start date (YYYY-MM-DD, default: 2026-03-01)")
    parser.add_argument("--until", default=None, help="End date (YYYY-MM-DD, default: 2026-05-10)")
    parser.add_argument("--cash", type=float, default=float(INITIAL_CAPITAL), help=f"Initial capital (default: {INITIAL_CAPITAL})")
    args = parser.parse_args()

    run_backtest(
        symbol=args.symbol,
        interval=args.interval,
        since=args.since,
        until=args.until,
        cash=args.cash,
        days=args.days,
    )
