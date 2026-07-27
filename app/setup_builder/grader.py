from dataclasses import dataclass
from enum import IntEnum

from app.setup_builder.config import A, A_PLUS, SCORE_A, SCORE_A_PLUS, SKIP

@dataclass(frozen=True)
class GradeResult:
    grade: str
    score: int

class Grader:
    @staticmethod
    def grade(score: int) -> GradeResult:
        if score >= SCORE_A_PLUS:
            return GradeResult(A_PLUS, score)
        elif score >= SCORE_A:
            return GradeResult(A, score)
        else:
            return GradeResult(SKIP, score)