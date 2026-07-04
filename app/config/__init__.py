from __future__ import annotations

try:
    from app.config.strategy_config import (
        GRADE_RISK_MULTIPLIERS,
        MAX_RISK_MULTIPLIERS,
        SETUP_RISK_MULTIPLIERS,
    )
    from app.config.settings import SYMBOLS, INITIAL_CAPITAL, LEVERAGE, TP1_R, TP2_R
    from app.config.settings import RISK_PER_TRADE, MAX_OPEN_POSITIONS, MODE
except ImportError:  # pragma: no cover - fallback for script-style execution
    from config.strategy_config import (
        GRADE_RISK_MULTIPLIERS,
        MAX_RISK_MULTIPLIERS,
        SETUP_RISK_MULTIPLIERS,
    )
    from config.settings import SYMBOLS, INITIAL_CAPITAL, LEVERAGE, TP1_R, TP2_R
    from config.settings import RISK_PER_TRADE, MAX_OPEN_POSITIONS, MODE

STRATEGY_CONFIG: dict = {
    "grade_risk_multipliers": GRADE_RISK_MULTIPLIERS,
    "max_risk_multipliers": MAX_RISK_MULTIPLIERS,
    "setup_risk_multipliers": SETUP_RISK_MULTIPLIERS,
    "initial_capital": INITIAL_CAPITAL,
    "leverage": LEVERAGE,
    "tp1_r": TP1_R,
    "tp2_r": TP2_R,
    "risk_per_trade": RISK_PER_TRADE,
    "max_open_positions": MAX_OPEN_POSITIONS,
}

__all__ = [
    "STRATEGY_CONFIG",
    "SYMBOLS",
    "GRADE_RISK_MULTIPLIERS",
    "MAX_RISK_MULTIPLIERS",
    "SETUP_RISK_MULTIPLIERS",
]
