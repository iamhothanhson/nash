# setup_scoring.py

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SetupScore:
    name: str
    score: int

@dataclass(frozen=True, slots=True)
class BreakoutScoreFeatures:
    close_above_level: bool
    breakout_strength: float
    volume_ratio: float
    rsi: float
    ema20_slope: float
    direction: str
    atr_expansion: bool = False
    market_trend_ok: bool = True


@dataclass(frozen=True, slots=True)
class BreakoutRetestScoreFeatures:
    breakout_was_valid: bool
    retest_touch: bool
    rejection_candle: bool
    volume_ratio: float
    rsi: float
    ema20_slope: float
    direction: str
    retest_distance_atr: float
    market_trend_ok: bool = True


@dataclass(frozen=True, slots=True)
class PullbackScoreFeatures:
    trend_ok: bool
    pullback_to_ema: bool
    reclaim_candle: bool
    rsi: float
    ema20_slope: float
    ema50_slope: float
    volume_ratio: float
    direction: str
    distance_from_ema: float


class SetupScoring:
    MAX_SCORE = 100

    @classmethod
    def score_candidate(
        cls,
        candidate,
    ) -> float:
        setup_type = str(candidate.setup_type)
        direction = str(candidate.direction)
        factors =  candidate.features

        if setup_type == "breakout":
            return cls.score_breakout(factors)

        if setup_type == "pullback":
            return cls.score_pullback(factors)

        if setup_type in {"breakout_retest", "retest"}:
            return cls.score_breakout_retest(factors)

        return 0.0


    @classmethod
    def score_breakout(cls, factors: BreakoutScoreFeatures) -> SetupScore:
        score = 0

        if factors.close_above_level:
            score += 25

        if factors.breakout_strength >= 0.006:
            score += 20
        elif factors.breakout_strength >= 0.004:
            score += 12

        if factors.volume_ratio >= 1.5:
            score += 20
        elif factors.volume_ratio >= 1.25:
            score += 12

        if factors.direction == "LONG":
            if factors.rsi >= 60:
                score += 15
            elif factors.rsi >= 55:
                score += 10
        else:
            if factors.rsi <= 40:
                score += 15
            elif factors.rsi <= 45:
                score += 10

        if factors.direction == "LONG" and factors.ema20_slope > 0:
            score += 10
        elif factors.direction == "SHORT" and factors.ema20_slope < 0:
            score += 10

        if factors.atr_expansion:
            score += 5

        if factors.market_trend_ok:
            score += 5

        return SetupScore(
            name="BREAKOUT",
            score=cls.clamp(score),
        )

    @classmethod
    def score_breakout_retest(cls, factors: BreakoutRetestScoreFeatures) -> SetupScore:
        score = 0

        if factors.breakout_was_valid:
            score += 20

        if factors.retest_touch:
            score += 20

        if factors.retest_distance_atr <= 0.2:
            score += 15
        elif factors.retest_distance_atr <= 0.35:
            score += 8

        if factors.rejection_candle:
            score += 20

        if factors.volume_ratio >= 1.25:
            score += 10
        elif factors.volume_ratio >= 1.0:
            score += 5

        if factors.direction == "LONG":
            if factors.rsi >= 55:
                score += 10
        else:
            if factors.rsi <= 45:
                score += 10

        if factors.direction == "LONG" and factors.ema20_slope > 0:
            score += 5
        elif factors.direction == "SHORT" and factors.ema20_slope < 0:
            score += 5

        if factors.market_trend_ok:
            score += 5

        return SetupScore(
            name="BREAKOUT_RETEST",
            score=cls.clamp(score),
        )

    @classmethod
    def score_pullback(cls, factors: PullbackScoreFeatures) -> SetupScore:
        score = 0

        if factors.trend_ok:
            score += 25

        if factors.pullback_to_ema:
            score += 20

        if factors.distance_from_ema <= 0.003:
            score += 15
        elif factors.distance_from_ema <= 0.006:
            score += 8

        if factors.reclaim_candle:
            score += 20

        if factors.direction == "LONG":
            if factors.ema20_slope > 0 and factors.ema50_slope > 0:
                score += 10
            if factors.rsi >= 50:
                score += 10
        else:
            if factors.ema20_slope < 0 and factors.ema50_slope < 0:
                score += 10
            if factors.rsi <= 50:
                score += 10

        if factors.volume_ratio >= 1.1:
            score += 5

        return SetupScore(
            name="PULLBACK",
            score=cls.clamp(score),
        )
    
    @classmethod
    def clamp(cls, score: int) -> int:
        return min(score, cls.MAX_SCORE)