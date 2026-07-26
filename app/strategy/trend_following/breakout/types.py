from dataclasses import dataclass


@dataclass
class BreakoutPipelineStats:
    candidates: int = 0
    long_candidates: int = 0
    short_candidates: int = 0
    hard_pass: int = 0
    soft_pass: int = 0
    setups: int = 0