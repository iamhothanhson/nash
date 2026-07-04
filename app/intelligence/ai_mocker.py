from __future__ import annotations

from typing import Any


def evaluate_trade(trade_data: dict[str, Any]) -> dict[str, Any]:
    """
    Same contract as ``ai_evaluator.evaluate_trade``: one ``trade_data`` dict in,
    ``{decision, confidence, reasoning}`` out (TAKE | SKIP).
    """
    min_confidence = float(trade_data.get("min_confidence", 0.55))

    direction = str(
        trade_data.get("direction") or trade_data.get("trend") or ""
    ).upper()
    entry = float(trade_data.get("entry", 0) or 0)
    stop_loss = float(trade_data.get("stop_loss", 0) or 0)
    tp1 = float(trade_data.get("tp1", 0) or 0)

    setup_score = float(trade_data.get("setup_score", 0) or 0)
    r_multiple = float(trade_data.get("r_multiple", 0) or 0)
    structure = float(
        trade_data.get("structure_quality")
        or trade_data.get("structure")
        or 0.5
    )
    entry_quality = float(
        trade_data.get("entry_cleanliness")
        or trade_data.get("entry_quality")
        or 0.5
    )

    if direction not in {"LONG", "SHORT"}:
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "invalid direction",
        }

    if entry <= 0 or stop_loss <= 0 or tp1 <= 0:
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "invalid price levels",
        }

    if setup_score <= 0:
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "no setup quality",
        }

    quality = (
        setup_score * 0.4
        + r_multiple * 2.0
        + structure * 2.5
        + entry_quality * 2.5
    )
    max_quality = 15.0
    confidence = quality / max_quality

    risk = abs(entry - stop_loss)
    reward = abs(tp1 - entry)

    if risk == 0:
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "zero risk",
        }

    rr = reward / risk

    if rr < 1.2:
        confidence *= 0.85
    elif rr > 2.5:
        confidence += 0.03

    if setup_score < 8:
        confidence *= 0.95

    if setup_score >= 9:
        confidence += 0.05

    confidence = max(0.0, min(confidence, 1.0))

    if confidence >= min_confidence:
        return {
            "decision": "TAKE",
            "confidence": round(confidence, 4),
            "reasoning": "confidence above threshold",
        }
    return {
        "decision": "SKIP",
        "confidence": round(confidence, 4),
        "reasoning": "confidence below threshold",
    }


if __name__ == "__main__":
    import json

    demo = {
        "direction": "LONG",
        "entry": 25000.0,
        "stop_loss": 24500.0,
        "tp1": 26000.0,
        "r_multiple": 1.5,
        "setup_score": 9,
        "min_confidence": 0.55,
        "structure_quality": 0.7,
        "entry_cleanliness": 0.6,
    }
    print(json.dumps(evaluate_trade(demo), indent=2))
