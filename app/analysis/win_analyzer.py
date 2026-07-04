"""
Win Analyzer — post-trade analytics for winning positions.

Appends an ``analysis`` block with factors that contributed to the win.
Post-trade analytics only — never affects live trading.
"""

from __future__ import annotations

from typing import Any


def analyze_win_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Run win analysis on a collected win record.
    Returns a copy with ``analysis`` appended.
    """
    mr = record.get("market_regime", {})
    tc = record.get("trade_context", {})
    tp = record.get("trade_performance", {})

    direction = tc.get("side", "LONG")
    is_long = direction.upper() == "LONG"
    mfe_r = tp.get("mfe_r", 0.0)
    mae_r = tp.get("mae_r", 0.0)
    bars_held = tc.get("bars_held", 0)
    pnl = tc.get("pnl_usdt", 0.0)
    risk_pct = tc.get("risk_pct", 0.0)

    regime = mr.get("regime", "Unknown")
    trend_dir = mr.get("trend_direction", "Neutral")
    mkt = mr.get("market_structure", "Range")
    adx = mr.get("adx_1h", mr.get("adx", 0.0))
    vol = mr.get("volume_ratio", 1.0)
    atr_pctl = mr.get("atr_percentile", 50)
    rsi = mr.get("rsi", 50.0)
    ema_slp = mr.get("ema20_slope_1h", mr.get("ema_slope", 0.0))

    factors: list[dict[str, str]] = []

    if regime in ("Strong Bullish", "Strong Bearish"):
        factors.append({
            "severity": "High",
            "message": f"Regime = {regime} — strong directional market environment.",
        })
    elif regime in ("Moderate Bullish", "Moderate Bearish"):
        factors.append({
            "severity": "Medium",
            "message": f"Regime = {regime} — moderate directional support.",
        })

    aligned = (is_long and trend_dir == "Bullish") or (not is_long and trend_dir == "Bearish")
    if aligned:
        factors.append({
            "severity": "High",
            "message": f"Trend direction ({trend_dir}) aligned with trade direction.",
        })

    if mkt in ("HHHL", "LHLL"):
        factors.append({
            "severity": "Medium",
            "message": f"Market structure ({mkt}) provided structural edge.",
        })

    if adx > 25:
        factors.append({
            "severity": "High",
            "message": f"ADX = {adx:.1f} (strong trend momentum).",
        })
    elif adx > 22:
        factors.append({
            "severity": "Medium",
            "message": f"ADX = {adx:.1f} (moderate trend momentum).",
        })

    if vol > 1.5:
        factors.append({
            "severity": "High",
            "message": f"Volume ratio = {vol:.2f} (strong institutional participation).",
        })
    elif vol > 1.2:
        factors.append({
            "severity": "Medium",
            "message": f"Volume ratio = {vol:.2f} (above-average participation).",
        })

    if (is_long and 40 <= rsi <= 60) or (not is_long and 40 <= rsi <= 60):
        factors.append({
            "severity": "Medium",
            "message": f"RSI = {rsi:.1f} (entry in neutral zone — room for move).",
        })
    elif (is_long and rsi < 40) or (not is_long and rsi > 60):
        factors.append({
            "severity": "Low",
            "message": f"RSI = {rsi:.1f} (entry at favorable extreme).",
        })

    if atr_pctl < 70:
        factors.append({
            "severity": "Low",
            "message": f"ATR percentile = {atr_pctl} (normal volatility, predictable movement).",
        })

    if mfe_r > 2.0:
        factors.append({
            "severity": "High",
            "message": f"MFE = +{mfe_r:.2f}R (strong favorable movement).",
        })
    elif mfe_r > 1.0:
        factors.append({
            "severity": "Medium",
            "message": f"MFE = +{mfe_r:.2f}R (good favorable movement).",
        })

    if 3 <= bars_held <= 24:
        factors.append({
            "severity": "Low",
            "message": f"Held {bars_held} bars — thesis had time to develop.",
        })

    if abs(ema_slp) > 0.002:
        factors.append({
            "severity": "Medium",
            "message": f"EMA slope = {ema_slp:.4f} (strong directional bias at entry).",
        })

    key_factors = sorted(factors, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}[x["severity"]])

    out = dict(record)
    out["analysis"] = {
        "direction_accuracy": "bullish" if aligned else "bearish" if trend_dir else "neutral",
        "factor_count": len(key_factors),
        "key_factors": key_factors,
    }
    return out
