from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class TestBacktestKPIGuardrailsRegression:
    def _run_backtest(self, days: int) -> str:
        env = os.environ.copy()
        env["MODE"] = "backtest"
        env["DATA_SOURCE"] = "history"
        env["HISTORY_AUTO_FETCH"] = "false"
        env["AI_ENABLED"] = "false"
        env["ALLOWED_SYMBOLS"] = "TAOUSDT"
        env["SYMBOLS"] = "TAOUSDT"
        proc = subprocess.run(
            [
                sys.executable,
                "app/backtesting/backtest.py",
                "--days",
                str(days),
                "--all",
                "--exit-tuning",
                "on",
            ],
            cwd=str(PROJECT_ROOT),
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
        return proc.stdout

    @staticmethod
    def _number(label: str, output: str) -> float:
        m = re.search(rf"^{label}:\s*([+\-]?[0-9]+(?:\.[0-9]+)?)", output, flags=re.MULTILINE)
        if not m:
            raise AssertionError(f"Missing metric '{label}' in output:\n{output}")
        return float(m.group(1))

    def test_backtest_30d_kpis_within_guardrails(self) -> None:
        out = self._run_backtest(30)
        roi = self._number("ROI", out)
        trades_per_day = self._number("Trades per Day", out)
        win_rate = self._number("Win Rate", out)
        profit_factor = self._number("Profit Factor", out)
        drawdown = self._number("Max Drawdown", out)
        trades = self._number("Total Trades", out)
        assert roi >= 45.0
        assert trades >= 75.0
        assert trades_per_day >= 2.5
        assert win_rate >= 60.0
        assert profit_factor >= 1.9
        assert drawdown <= 7.0

    def test_backtest_90d_no_crash_and_guardrails(self) -> None:
        out = self._run_backtest(90)
        roi = self._number("ROI", out)
        trades_per_day = self._number("Trades per Day", out)
        win_rate = self._number("Win Rate", out)
        profit_factor = self._number("Profit Factor", out)
        drawdown = self._number("Max Drawdown", out)
        trades = self._number("Total Trades", out)
        assert roi >= 280.0
        assert trades >= 400.0
        assert trades_per_day >= 4.5
        assert win_rate >= 57.0
        assert profit_factor >= 1.9
        assert drawdown <= 14.0
