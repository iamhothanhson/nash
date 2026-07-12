from __future__ import annotations

from dataclasses import dataclass

from app.core.types import Direction, MarketStructure


@dataclass(slots=True)
class BreakoutFeatures:
    direction: Direction
    breakout_level: float
    close_above_level: bool
    breakout_strength_pct: float
    distance_from_level_pct: float
    candle_body_ratio: float
    wick_ratio: float
    touch_count: int
    breakout_level_age: int
    market_structure: MarketStructure
    htf_confirmed: bool


@dataclass(slots=True)
class SetupFeatures:
    breakout: BreakoutFeatures

    @classmethod
    def empty(cls) -> SetupFeatures:
        return cls(
            breakout=BreakoutFeatures(
                direction="LONG",
                breakout_level=0.0,
                close_above_level=False,
                breakout_strength_pct=0.0,
                distance_from_level_pct=0.0,
                candle_body_ratio=0.0,
                wick_ratio=0.0,
                touch_count=0,
                breakout_level_age=0,
                market_structure="UNKNOWN",
                htf_confirmed=False,
            )
        )
