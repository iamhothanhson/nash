from __future__ import annotations


def grade_setup(setup) -> str:
    score = int(getattr(setup, "score", 0))
    if score >= 85:
        return "A+"
    if score >= 75:
        return "A"
    return "Skip"


grade_from_score = grade_setup
