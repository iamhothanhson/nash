from enum import Enum, auto

class TrailType(Enum):
    NONE = auto()
    BREAK_EVEN = auto()
    ATR = auto()
    SWING = auto()

class RejectReason(Enum):
    STRUCTURE = auto()
    BREAKOUT_HARD_LONG = auto()
    BREAKOUT_HARD_SHORT = auto()
    BREAKOUT_SOFT_LONG= auto()
    BREAKOUT_SOFT_SHORT = auto()
    SCORE = auto()
    RISK = auto()

class RejectionStage(Enum):
    HARD_LONG = "HARD_LONG"
    HARD_SHORT = "HARD_SHORT"
    SOFT_LONG = "SOFT_LONG"
    SOFT_SHORT = "SOFT_SHORT"