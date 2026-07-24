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

from analysis.collect_position_metrics import clear_analysis_file
from backtesting.executor import BacktestExecutor
from backtesting.marketplace import HistoricalMarketplace
from backtesting.position import BacktestPositionManager
from backtesting.trading_pipeline import BacktestTradingPipeline
from backtesting.config import BACKTEST_END, INDICATOR_WARMUP_BARS
from backtesting.utils import print_result
from core.logging import setup_logging


HISTORY_DIR = Path(__file__).resolve().parent / "history_data"


def main() -> None:
    setup_logging(console=False, clean=True)
    parser = argparse.ArgumentParser(description="Run backtest")
    parser.add_argument("--symbol", type=str, default=None, help="Symbol to backtest (e.g. TAOUSDT)")
    parser.add_argument("--days", type=int, default=None, help="Number of recent days to backtest")
    args = parser.parse_args()

    clear_analysis_file()

    mp = HistoricalMarketplace.from_csv_dir(HISTORY_DIR)
    if not mp.data:
        print("No backtest data found in history_data")
        return

    initial_balance = float(os.environ.get("INITIAL_CAPITAL", "100"))
    portfolio = BacktestPositionManager(initial_balance=initial_balance)
    executor = BacktestExecutor()

    if args.symbol:
        if args.symbol not in mp.data:
            print(f"Symbol {args.symbol} not found in history_data")
            return
        symbols = [args.symbol]
    else:
        symbols = list(mp.data.keys())

    first_tf = next(iter(mp.data[symbols[0]].values()))
    timestamps = first_tf.index[INDICATOR_WARMUP_BARS:]

    end_dt = __import__("pandas").Timestamp(BACKTEST_END)
    timestamps = timestamps[timestamps <= end_dt]

    if args.days:
        cutoff = timestamps[-1] - __import__("pandas").Timedelta(days=args.days)
        timestamps = timestamps[timestamps >= cutoff]

    pipeline = BacktestTradingPipeline(
        marketplace=mp, portfolio=portfolio, executor=executor,
    )
    result = pipeline.run(symbols=symbols, timestamps=timestamps)
    result["initial_balance"] = initial_balance
    print_result(result)


if __name__ == "__main__":
    main()
