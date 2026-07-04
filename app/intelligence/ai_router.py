from __future__ import annotations

from typing import Any

from config import settings
from intelligence.ai_filter import ai_gate_score_tier, ai_gate_trade_metrics
from intelligence.ai_evaluator import evaluate_trade as evaluate_openai_trade
from intelligence.ai_mocker import evaluate_trade as evaluate_mock_trade


def evaluate_trade(trade_data: dict[str, Any]) -> dict[str, Any]:
    mode = settings.AI_MODE

    # Use SKIP (not HOLD) so callers that only check `decision == "SKIP"` stay aligned
    # with mock/OpenAI (TAKE | SKIP). Same dict shape for every exit path.
    if not ai_gate_score_tier(trade_data):
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "invalid_score_tier",
        }

    if not ai_gate_trade_metrics(trade_data):
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "invalid_trade_metrics",
        }

    if mode == "mock":
        return evaluate_mock_trade(trade_data)

    if mode == "openai":
        return evaluate_openai_trade(trade_data)

    raise ValueError(f"Invalid AI_MODE '{mode}'. Expected one of: mock, openai.")
