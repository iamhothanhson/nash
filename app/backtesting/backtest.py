from __future__ import annotations

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


HISTORY_DIR = Path(__file__).resolve().parent / "history_data"


def main() -> None:
    mp = HistoricalMarketplace.from_csv_dir(HISTORY_DIR)
    if not mp.data:
        print("No backtest data found in history_data")
        return

    portfolio = BacktestPortfolio(initial_balance=10000.0)
    executor = BacktestExecutor()

    symbols = list(mp.data.keys())
    first_tf = next(iter(mp.data[symbols[0]].values()))
    timestamps = first_tf.index[200:]

    pipeline = BacktestTradingPipeline(
        marketplace=mp, portfolio=portfolio, executor=executor,
    )
    result = pipeline.run(symbols=symbols, timestamps=timestamps)
    _print_result(result)


def _print_result(result: dict) -> None:
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


if __name__ == "__main__":
    main()
