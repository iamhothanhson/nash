from enum import Enum, auto

class TrailType(Enum):
    NONE = auto()
    BREAK_EVEN = auto()
    ATR = auto()
    SWING = auto()

class RejectReason(Enum):
    STRUCTURE = auto()
    BREAKOUT_HARD = auto()
    BREAKOUT_SHORT = auto()
    SCORE = auto()
    RISK = auto()

class RejectionStage(Enum):
    HARD = "HARD"
    SOFT = "SOFT"