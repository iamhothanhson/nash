"""
Print risk multiplier flow for each setup/grade combination.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
APP_PATH = PROJECT_ROOT / "app"
if str(APP_PATH) not in sys.path:
    sys.path.insert(0, str(APP_PATH))

from config import settings
from risk_manager.config import (
    GRADE_RISK_MULTIPLIERS,
    MAX_RISK_MULTIPLIERS,
    SETUP_RISK_MULTIPLIERS,
)


BASE = float(settings.RISK_PER_TRADE)
MAX_EXEC = float(settings.MAX_EXECUTION_RISK_PER_TRADE)
CAPITAL = float(settings.INITIAL_CAPITAL)
REGIME_MAX = 1.40
COIN_MAX = 1.15
EXEC_CAP_PCT = MAX_EXEC * 100.0

SETUP_KEY_MAP = {
    "Breakout": "breakout",
    "Pullback": "pullback",
    "Breakout Retest": "breakout_retest",
    "Liquidity Sweep": "liquidity_sweep_reversal",
}

GRADE_KEY_MAP = {
    "A+": "A+",
    "A": "A",
    "A+/A": "A+",
}

ROWS = [
    ("Breakout",        "A+",   GRADE_RISK_MULTIPLIERS["A+"], SETUP_RISK_MULTIPLIERS["breakout"]),
    ("Breakout",        "A",    GRADE_RISK_MULTIPLIERS["A"],   SETUP_RISK_MULTIPLIERS["breakout"]),
    ("Pullback",        "A+",   GRADE_RISK_MULTIPLIERS["A+"], SETUP_RISK_MULTIPLIERS["pullback"]),
    ("Pullback",        "A",    GRADE_RISK_MULTIPLIERS["A"],   SETUP_RISK_MULTIPLIERS["pullback"]),
    ("Breakout Retest", "A+",   GRADE_RISK_MULTIPLIERS["A+"], SETUP_RISK_MULTIPLIERS["breakout_retest"]),
    ("Breakout Retest", "A",    GRADE_RISK_MULTIPLIERS["A"],   SETUP_RISK_MULTIPLIERS["breakout_retest"]),
    ("Liquidity Sweep", "A+/A", None,                          1.40),  # MarketRegime.risk_multiplier max
]


def fmt_mult(v: float | None, width: int = 11) -> str:
    if v is None:
        return "—".center(width)
    return f"{v:.2f}×".rjust(width)


def fmt_pct(v: float, width: int = 9) -> str:
    return f"{v:.2f}%".rjust(width)


header = (
    f"{'Setup':<18} {'Grade':<7} {'Grade Mult':>11} {'Setup Mult':>11} "
    f"{'Regime Mult':>11} {'Coin Mult':>11} {'Total Mult':>11} "
    f"{'Mult Cap':>11} {'Calc Risk':>11} {'Max Cap':>9} {'Final Risk':>11}"
)
SEP = "─" * len(header)

print(f"\nCapital: ${CAPITAL:,.2f}     Base Risk: {BASE*100:.2f}%     Max Exec Risk: {MAX_EXEC*100:.2f}%\n")
print(header)
print(SEP)

for setup, grade, grade_mult, setup_mult in ROWS:
    setup_key = SETUP_KEY_MAP[setup]
    grade_key = GRADE_KEY_MAP[grade]
    max_mult = MAX_RISK_MULTIPLIERS[setup_key][grade_key]
    max_cap_pct = max_mult * BASE * 100.0

    if setup == "Liquidity Sweep":
        grade_mult_val = None
        setup_mult_val = setup_mult
        total = 1.0 * setup_mult_val * REGIME_MAX * COIN_MAX
    else:
        grade_mult_val = grade_mult
        setup_mult_val = setup_mult
        total = grade_mult_val * setup_mult_val * REGIME_MAX * COIN_MAX

    capped_mult = min(total, max_mult)
    calc_risk = BASE * capped_mult * 100.0
    final = min(calc_risk, EXEC_CAP_PCT)

    row = (
        f"{setup:<18} {grade:<7} "
        f"{fmt_mult(grade_mult_val)} {fmt_mult(setup_mult_val)} "
        f"{fmt_mult(REGIME_MAX)} {fmt_mult(COIN_MAX)} "
        f"{fmt_mult(total)} {fmt_mult(max_mult)} "
        f"{fmt_pct(calc_risk)} {fmt_pct(max_cap_pct)} "
        f"{fmt_pct(final)}"
    )
    print(row)


