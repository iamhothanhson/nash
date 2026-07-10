
# Backtesting
python3 app/backtesting/backtest.py
--all
--symbol RENDER backtest_symbol.json
--portfolio
--days # 7,30,90
--fetch RENDER
--fetch all # Download all settings.SYMBOLS
--log
--baseline
--ai
--daily-stat # Performance/05-2026_statistics.json
--exit-metrics # File data/baseline/backtest_exit_metrics.json
# Wire to backtest_exit_baseline.json
--exit-baseline
# Wire to backtest_symbol_baseline.json
--symbol-baseline
--since 2026-04-01 --until 2026-05-01