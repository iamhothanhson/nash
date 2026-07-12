from dataclasses import dataclass

from app.strategy.models import SetupCandidate


@dataclass(frozen=True)
class ScoreResult:
    score: float
    strength: str
    confirmation_mode: str


class BreakoutScorer:
    def score(self, candidate: SetupCandidate) -> ScoreResult:
        score = 0

        if candidate.breakout_strength >= 0.004:
            score += 15

        if candidate.volume_ratio >= 1.25:
            score += 15

        if candidate.rsi >= 55:
            score += 10

        if candidate.ema_slope > 0:
            score += 10

        if candidate.trend_aligned:
            score += 10

        score = min(score, 100)

        return ScoreResult(
            score=score
        )