
from dataclasses import dataclass, field
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from app.core.enums import RejectionStage
from app.core.types import RejectionMetric


@dataclass
class BreakoutRejection:
    timestamp: datetime
    symbol: str
    side: str   # LONG / SHORT
    stage: RejectionStage
    reasons: list[str]
    metrics: list[RejectionMetric] = field(default_factory=list)


class BreakoutRejectionAnalyzer:

    def __init__(self):
        self.items: list[BreakoutRejection] = []

    def add(
        self,
        timestamp: datetime,
        symbol: str,
        side: str,
        stage: str,
        reasons: list[str],
        metrics: list[RejectionMetric] | None = None,
    ):
        self.items.append(
            BreakoutRejection(
                timestamp=timestamp,
                symbol=symbol,
                side=side,
                stage=stage,
                reasons=reasons,
                metrics=metrics
            )
        )

    def summary(self) -> dict[str, list[tuple[str, int, float]]]:
        groups: dict[tuple[str, str], dict[str, int]] = {}
        group_counts: dict[tuple[str, str], int] = {}

        for item in self.items:
            key = (item.stage.value if hasattr(item.stage, 'value') else str(item.stage), item.side)
            if key not in groups:
                groups[key] = {}
                group_counts[key] = 0
            group_counts[key] += 1
            for reason in item.reasons:
                name = reason.split(" ")[0]
                groups[key][name] = groups[key].get(name, 0) + 1

        result = {}
        for key, reasons in groups.items():
            stage, side = key
            total = group_counts[key]
            items = [(r, c, c / total * 100) for r, c in sorted(reasons.items(), key=lambda x: -x[1])]
            result[f"{stage}_{side}"] = items

        return result

    def metric_summary(self):
        stats = defaultdict(list)

        for item in self.items:
            for metric in item.metrics:
                stats[metric.name].append(metric.value)

        return stats