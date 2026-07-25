from collections import Counter


class MarketStructureDebug:
    def __init__(self):
        self.reasons = Counter()

    def record(
        self,
        recent_highs: list,
        recent_lows: list,
        high_score: int,
        low_score: int,
    ) -> None:
        if len(recent_highs) < 3:
            self.reasons["few_highs"] += 1
            return

        if len(recent_lows) < 3:
            self.reasons["few_lows"] += 1
            return

        if high_score >= 2 and low_score >= 2:
            self.reasons["HHHL"] += 1
            return

        if high_score <= -2 and low_score <= -2:
            self.reasons["LHLL"] += 1
            return

        # Record the exact score combination
        key = f"H{high_score:+d}_L{low_score:+d}"
        self.reasons[key] += 1

    def print_summary(self) -> None:
        print("\n Market Structure Summary")
        total = sum(self.reasons.values())

        for k, v in sorted(self.reasons.items()):
            pct = (v / total * 100) if total else 0
            print(f"{k:<12}: {v:>6} ({pct:5.1f}%)")