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


@dataclass(frozen=True, slots=True)
class LiquiditySweepReversalScoreFeatures:
    sweep_happened: bool
    reclaim_level: bool
    rejection_wick_ratio: float
    volume_ratio: float
    rsi_divergence: bool
    direction: str
    near_support_resistance: bool
    market_overextended: bool = False


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
            return cls._score_breakout(factors, direction)

        if setup_type == "pullback":
            return cls._score_pullback(factors, direction)

        if setup_type in {"liquidity_sweep", "sweep"}:
            return cls._score_sweep(factors, direction)

        if setup_type in {"breakout_retest", "retest"}:
            return cls._score_retest(factors, direction)

        return 0.0


    @classmethod
    def score_breakout(cls, f: BreakoutScoreFeatures) -> SetupScore:
        score = 0

        if f.close_above_level:
            score += 25

        if f.breakout_strength >= 0.006:
            score += 20
        elif f.breakout_strength >= 0.004:
            score += 12

        if f.volume_ratio >= 1.5:
            score += 20
        elif f.volume_ratio >= 1.25:
            score += 12

        if f.direction == "LONG":
            if f.rsi >= 60:
                score += 15
            elif f.rsi >= 55:
                score += 10
        else:
            if f.rsi <= 40:
                score += 15
            elif f.rsi <= 45:
                score += 10

        if f.direction == "LONG" and f.ema20_slope > 0:
            score += 10
        elif f.direction == "SHORT" and f.ema20_slope < 0:
            score += 10

        if f.atr_expansion:
            score += 5

        if f.market_trend_ok:
            score += 5

        return SetupScore(
            name="BREAKOUT",
            score=cls.clamp(score),
        )

    @classmethod
    def score_breakout_retest(cls, f: BreakoutRetestScoreFeatures) -> SetupScore:
        score = 0

        if f.breakout_was_valid:
            score += 20

        if f.retest_touch:
            score += 20

        if f.retest_distance_atr <= 0.2:
            score += 15
        elif f.retest_distance_atr <= 0.35:
            score += 8

        if f.rejection_candle:
            score += 20

        if f.volume_ratio >= 1.25:
            score += 10
        elif f.volume_ratio >= 1.0:
            score += 5

        if f.direction == "LONG":
            if f.rsi >= 55:
                score += 10
        else:
            if f.rsi <= 45:
                score += 10

        if f.direction == "LONG" and f.ema20_slope > 0:
            score += 5
        elif f.direction == "SHORT" and f.ema20_slope < 0:
            score += 5

        if f.market_trend_ok:
            score += 5

        return SetupScore(
            name="BREAKOUT_RETEST",
            score=cls.clamp(score),
        )

    @classmethod
    def score_pullback(cls, f: PullbackScoreFeatures) -> SetupScore:
        score = 0

        if f.trend_ok:
            score += 25

        if f.pullback_to_ema:
            score += 20

        if f.distance_from_ema <= 0.003:
            score += 15
        elif f.distance_from_ema <= 0.006:
            score += 8

        if f.reclaim_candle:
            score += 20

        if f.direction == "LONG":
            if f.ema20_slope > 0 and f.ema50_slope > 0:
                score += 10
            if f.rsi >= 50:
                score += 10
        else:
            if f.ema20_slope < 0 and f.ema50_slope < 0:
                score += 10
            if f.rsi <= 50:
                score += 10

        if f.volume_ratio >= 1.1:
            score += 5

        return SetupScore(
            name="PULLBACK",
            score=cls.clamp(score),
        )

    @classmethod
    def score_liquidity_sweep_reversal(
        cls,
        f: LiquiditySweepReversalScoreFeatures,
    ) -> SetupScore:
        score = 0

        if f.sweep_happened:
            score += 25

        if f.reclaim_level:
            score += 25

        if f.rejection_wick_ratio >= 0.55:
            score += 20
        elif f.rejection_wick_ratio >= 0.35:
            score += 10

        if f.volume_ratio >= 1.5:
            score += 15
        elif f.volume_ratio >= 1.2:
            score += 8

        if f.rsi_divergence:
            score += 10

        if f.near_support_resistance:
            score += 10

        if f.market_overextended:
            score += 5

        return SetupScore(
            name="LIQUIDITY_SWEEP_REVERSAL",
            score=cls.clamp(score),
        )

    
    @classmethod
    def clamp(cls, score: int) -> int:
        return min(score, cls.MAX_SCORE)