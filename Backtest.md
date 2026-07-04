
# Backtesting CLI
python3 app/backtesting/backtest.py
--all
--symbol RENDER # Full portfolio run; detailed report + artifacts/backtest_symbol.json
--symbol RENDER --only # Simulate RENDER only, no portfolio competition
--portfolio
--days # 7-30-90
--fetch RENDER # Download RENDERUSDT CSVs (HISTORY_AUTO_FETCH=true), then backtest
--fetch all # Download all settings.SYMBOLS
--log
--baseline
--ai
--daily-stat # Performance/05-2026_statistics.json
--exit-metrics # File artifacts/backtest_exit_metrics.json
# Wire to backtest_exit_baseline.json
--exit-baseline
# Wire to backtest_symbol_baseline.json
--symbol-baseline