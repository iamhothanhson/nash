from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backtrader as bt
import pandas as pd
from config.settings import INITIAL_CAPITAL

from indicators.indicator_builder import IndicatorBuilder
from market_analyzer.feature_builder import build_features
from market_analyzer.market_analyzer import (
    _trend_direction,
    _classify_regime,
    _regime_confidence,
    _map_regime,
)
from market_analyzer.market_state import (
    MarketState,
    TrendDirection,
    MarketRegime,
    MarketStructure,
)
from market_analyzer.market_structure import detect_market_structure
from market_analyzer.market_trend import calculate_adx
from strategy.trend_following.breakout.config import BREAKOUT_LONG, BREAKOUT_SHORT
from strategy.trend_following.breakout.detector import BreakoutDetector


HISTORY_DIR = Path(__file__).resolve().parent / "history_data"


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


class BreakoutBT(bt.Strategy):
    params = (
        ("risk_per_trade", 0.01),
        ("sl_atr_mult", 1.5),
        ("min_history", 60),
    )

    def __init__(self):
        self.detector = BreakoutDetector()

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
        features = build_features(data_15m=df, indicators=indicators)

        ema_slp = float(indicators.get("ema20_slope_15m", 0.0))
        vol_r = indicators.get("volume_ratio", 1.0)
        atr_pctl = indicators.get("atr_percentile", 50)
        adx_v = (
            float(calculate_adx(df, 14).iloc[-1])
            if len(df) >= 14
            else 0.0
        )
        ms_15m = detect_market_structure(df["high"], df["low"])

        trend_dir_str = _trend_direction(ema_slp)
        trend_dir = (
            TrendDirection.BULLISH
            if trend_dir_str.lower() == "bullish"
            else TrendDirection.BEARISH
            if trend_dir_str.lower() == "bearish"
            else TrendDirection.NEUTRAL
        )
        regime_str = _classify_regime(adx_v, atr_pctl, ema_slp, trend_dir_str, ms_15m)
        regime = _map_regime(regime_str)

        is_trending = regime in (
            MarketRegime.STRONG_BULLISH,
            MarketRegime.BULLISH,
            MarketRegime.BEARISH,
            MarketRegime.STRONG_BEARISH,
        )

        return MarketState(
            symbol=symbol,
            timestamp=int(pd.Timestamp(df.index[-1]).timestamp() * 1000),
            timeframe="15m",
            trend_direction=trend_dir,
            trend_aligned=True,
            regime=regime,
            structure=MarketStructure.UNKNOWN,
            regime_confidence=float(
                _regime_confidence(adx_v, ema_slp, vol_r, ms_15m, trend_dir_str)
            ),
            is_trending=is_trending,
            is_ranging=regime == MarketRegime.RANGE,
            is_high_volatility=regime == MarketRegime.HIGH_VOLATILITY_CHOP,
            indicators=indicators,
            features=features,
            data_15m=df,
        )

    def next(self):
        if len(self.data) < self.p.min_history:
            return

        ms = self._build_market_state()
        if ms is None or ms.features is None:
            return

        candidate = self.detector.breakout_long_candidate(ms) or self.detector.breakout_short_candidate(ms)
        if candidate is None:
            return

        if self.position:
            return

        cfg = BREAKOUT_LONG if candidate.direction == "LONG" else BREAKOUT_SHORT
        close = self.data.close[0]
        atr_pct = float(ms.indicators.get("atr_percent", 0.0))

        sl_distance = max(
            cfg.get("min_sl_distance", 0.003),
            atr_pct * self.p.sl_atr_mult,
        )
        sl_price = close - sl_distance if candidate.direction == "LONG" else close + sl_distance

        value_per_risk = self.broker.getvalue() * self.p.risk_per_trade
        size = value_per_risk / close

        if candidate.direction == "LONG":
            self.buy(size=size, sl=sl_price)
        else:
            self.sell(size=size, sl=sl_price)


def run_backtest(
    symbol: str = "TAOUSDT",
    interval: str = "15m",
    since: str | None = None,
    until: str | None = None,
    cash: float = 10000.0,
    days: int | None = None,
) -> None:
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
    cerebro.addstrategy(BreakoutBT)
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=0.0004)

    print(f"Starting Value: ${cerebro.broker.getvalue():,.2f}")
    cerebro.run()
    print(f"Final Value:    ${cerebro.broker.getvalue():,.2f}")
    print(f"ROI:            {((cerebro.broker.getvalue() / cash) - 1) * 100:.2f}%")
    cerebro.plot()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run breakout backtest with backtrader")
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
