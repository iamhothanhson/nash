from dataclasses import dataclass


@dataclass(frozen=True)
class GradeResult:
    grade: str
    score: int


class Grader:
    @staticmethod
    def grade(score: int) -> GradeResult:
        if score >= 90:
            return GradeResult("A+", score)
        elif score >= 80:
            return GradeResult("A", score)
        else:
            return GradeResult("SKIP", score)