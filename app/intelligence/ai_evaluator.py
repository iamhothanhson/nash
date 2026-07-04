import os
import json
from typing import Optional

from openai import OpenAI

from config import settings

_client: Optional[OpenAI] = None


def _get_openai_client() -> Optional[OpenAI]:
    """Build client only when AI is on and a key exists (CI can import with AI_ENABLED=false)."""
    global _client
    if not bool(getattr(settings, "AI_ENABLED", False)):
        return None
    key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not key:
        return None
    if _client is None:
        _client = OpenAI(api_key=key)
    return _client


SYSTEM_PROMPT = """
You are a professional trading analyst.

Your job is to evaluate trade quality, not just basic validity.

Focus on:
- Structure quality
- Entry cleanliness
- Risk-reward quality
- Confirmation strength

Rules:
- Prefer high structure_quality and entry_cleanliness
- Prefer setup_score >= 8
- Be stricter when setup_score is borderline (8–10)

Return ONLY valid JSON in this format:
{
  "decision": "TAKE" or "SKIP",
  "confidence": float,
  "reasoning": string
}
"""


def evaluate_trade(trade_data: dict) -> dict:
    if not bool(getattr(settings, "AI_ENABLED", False)):
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "AI_ENABLED=false",
        }
    client = _get_openai_client()
    if client is None:
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": "OPENAI_API_KEY not set",
        }
    try:
        response = client.chat.completions.create(
            model=os.getenv("OPENAI_API_MODEL"),
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Evaluate this trade:\n{json.dumps(trade_data)}"
                }
            ],
            temperature=float(os.getenv("OPENAI_API_TEMPERATURE", "0.0")),
            timeout=10,
        )

        content = response.choices[0].message.content.strip()
        print(f"[OPENAI RAW] {content}")

        # Parse JSON safely
        result = json.loads(content)

        # Validate output
        if "decision" not in result:
            raise ValueError("Missing decision field")

        if "reasoning" not in result and "reason" in result:
            result = {**result, "reasoning": str(result["reason"])}
        elif "reasoning" not in result:
            result = {**result, "reasoning": ""}
        return result

    except Exception as e:
        # Fallback (VERY important for trading safety)
        print(f"[OPENAI ERROR] {str(e)}")
        return {
            "decision": "SKIP",
            "confidence": 0.0,
            "reasoning": f"AI error: {str(e)}"
        }