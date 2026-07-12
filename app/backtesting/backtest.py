from __future__ import annotations

import argparse
import os
import sys

BACKTESTING_DIR = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(BACKTESTING_DIR)
ROOT_DIR = os.path.dirname(APP_DIR)
for path in (APP_DIR, ROOT_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from pathlib import Path

from backtesting.executor import BacktestExecutor
from backtesting.marketplace import HistoricalMarketplace
from backtesting.portfolio import BacktestPortfolio
from backtesting.trading_pipeline import BacktestTradingPipeline
from backtesting.config import LOOKBACK
from backtesting.utils import print_result


HISTORY_DIR = Path(__file__).resolve().parent / "history_data"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--symbol", type=str, default=None, help="Symbol to backtest (e.g. TAOUSDT)")
    parser.add_argument("--days", type=int, default=None, help="Number of recent days to backtest")
    args = parser.parse_args()

    mp = HistoricalMarketplace.from_csv_dir(HISTORY_DIR)
    if not mp.data:
        print("No backtest data found in history_data")
        return

    portfolio = BacktestPortfolio(initial_balance=100)
    executor = BacktestExecutor()

    if args.symbol:
        if args.symbol not in mp.data:
            print(f"Symbol {args.symbol} not found in history_data")
            return
        symbols = [args.symbol]
    else:
        symbols = list(mp.data.keys())

    first_tf = next(iter(mp.data[symbols[0]].values()))
    timestamps = first_tf.index[LOOKBACK:]

    if args.days:
        cutoff = timestamps[-1] - __import__("pandas").Timedelta(days=args.days)
        timestamps = timestamps[timestamps >= cutoff]

    pipeline = BacktestTradingPipeline(
        marketplace=mp, portfolio=portfolio, executor=executor,
    )
    result = pipeline.run(symbols=symbols, timestamps=timestamps)
    print_result(result)


if __name__ == "__main__":
    main()
