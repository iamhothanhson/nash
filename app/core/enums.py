from enum import Enum, auto

class TrailType(Enum):
    NONE = auto()
    BREAK_EVEN = auto()
    ATR = auto()
    SWING = auto()

class RejectReason(Enum):
    STRUCTURE = auto()
    BREAKOUT = auto()
    SCORE = auto()
    RISK = auto()