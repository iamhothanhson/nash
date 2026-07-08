from __future__ import annotations

# MAX_RISK_MULTIPLIERS = {
#     "breakout": {
#         "A+": 3.0,
#         "A": 1.0
#     },
#     "pullback": {
#         "A+": 1.5,
#         "A": 1.0
#     },
#     "breakout_retest": {
#         "A+": 1.5,
#         "A": 1.00
#     },
#     "liquidity_sweep_reversal": {
#         "A+": 1.5,
#         "A": 1.0
#     },
# }

SETUP_RISK_MULTIPLIERS = {
    "breakout": 1.5,
    "breakout_retest": 1.0,
    "pullback": 0.8,
    "liquidity_sweep_reversal": 0.8
}

GRADE_RISK_MULTIPLIERS = {
    "A+": 1.5,
    "A": 1.0
}

MARKET_RISK_MULTIPLIERS = {
    "strong_trend": 1.5,
    "trend": 1.0,
    "range": 0.5
}
