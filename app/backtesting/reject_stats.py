from collections import Counter
from dataclasses import dataclass, field


@dataclass
class RejectStats:
    counters: Counter = field(default_factory=Counter)

    def reject(self, reason: str):
        self.counters[reason] += 1

    def accept(self):
        self.counters["accepted"] += 1

    def summary(self):
        print("\n===== Trade Filter Summary =====")

        order = [
            "structure",
            "breakout",
            "score",
            "risk",
            "position",
            "duplicate",
            "cooldown",
            "accepted",
        ]

        for key in order:
            if key in self.counters:
                print(f"{key.capitalize():<12}: {self.counters[key]}")

        print("\nOther Reasons:")
        for k, v in self.counters.items():
            if k not in order:
                print(f"{k:<12}: {v}")