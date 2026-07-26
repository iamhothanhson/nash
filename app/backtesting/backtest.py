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
from market_analyzer.market_structure import market_structure_debug
from strategy.trend_following.breakout.rejection import BreakoutRejectionAnalyzer


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
    position_manager = BacktestPositionManager(initial_balance=initial_balance)
    executor = BacktestExecutor(marketplace=mp, position_manager=position_manager)

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
        marketplace=mp, position_manager=position_manager, executor=executor,
    )
    result = pipeline.run(symbols=symbols, timestamps=timestamps)
    result["initial_balance"] = initial_balance
    print_result(result)
    if market_structure_debug:
        market_structure_debug.print_summary()


    breakout_rejection: BreakoutRejectionAnalyzer | None = result.get("breakout_rejection")
    if breakout_rejection and breakout_rejection.items:
        print("\n Breakout Rejection Summary")
        for group, reasons in breakout_rejection.summary().items():
            print(f"\n  {group}")
            for reason, count, pct in reasons:
                print(f"    {reason:<20} {count:>4} ({pct:5.1f}%)")

        for name, values in breakout_rejection.metric_summary().items():
            print(
                f"{name:<20} "
                f"avg={sum(values)/len(values):.2f} "
                f"min={min(values):.2f} "
                f"max={max(values):.2f}"
            )

    stats = result.get("pipeline_stats")
    if stats:
        total = stats.candidates or 1
        hard_pct = stats.hard_pass / total * 100
        soft_pct = stats.soft_pass / stats.hard_pass * 100 if stats.hard_pass else 0
        setup_pct = stats.setup_candidates / stats.soft_pass * 100 if stats.soft_pass else 0
        print("\n\nBREAKOUT PIPELINE")
        print(f"{'Candidates':<20} {stats.candidates}")
        print(f"  {'LONG':<18} {stats.long_candidates}")
        print(f"  {'SHORT':<18} {stats.short_candidates}")
        print(f"{'Hard pass':<20} {stats.hard_pass} ({hard_pct:.1f}%)")
        print(f"{'Soft pass':<20} {stats.soft_pass} ({soft_pct:.1f}%)")
        print(f"{'Setup candidates':<20} {stats.setup_candidates} ({setup_pct:.1f}%)")
        print(f"{'Setup built':<20} {stats.setup_built}")
        print(f"{'  skip no data':<20} {stats.setup_skip_no_data}")
        print(f"{'  skip no entry':<20} {stats.setup_skip_no_entry}")
        print(f"{'  skip score':<20} {stats.setup_skip_score}")
        if stats.setup_skip_score_values:
            vals = stats.setup_skip_score_values
            print(f"{'  Skipped Score Range':<20} {min(vals):.0f}-{max(vals):.0f} avg={sum(vals)/len(vals):.0f}")
        print(f"{'Signal built':<20} {stats.signal_built}")
        print(f"{'Risk allowed':<20} {stats.risk_allowed}")
        print(f"{'Order planned':<20} {stats.order_planned}")


if __name__ == "__main__":
    main()
