from collections import Counter
from dataclasses import dataclass, field


@dataclass
class BreakoutPipelineStats:
    candidates: int = 0
    long_candidates: int = 0
    short_candidates: int = 0
    hard_pass: int = 0
    soft_pass: int = 0
    setup_candidates: int = 0
    setup_built: int = 0
    setup_skip_no_data: int = 0
    setup_skip_no_entry: int = 0
    setup_skip_score: int = 0
    setup_skip_score_values: list[int] = field(default_factory=list)
    signal_built: int = 0
    signal_skip: int = 0
    signal_skip_reasons: Counter = field(default_factory=Counter)
    risk_allowed: int = 0
    order_planned: int = 0