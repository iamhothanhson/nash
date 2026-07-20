
from order_planner.models import OrderPlan

from analysis.collect_position_metrics import (
    build_entry_snapshot,
    save_entry_snapshot,
)


class EntrySnapshotService:
    @staticmethod
    def record_entry(
        plan: OrderPlan,
        *,
        symbol: str,
        direction: str,
    ) -> None:
        snapshot = build_entry_snapshot(
            plan.market_state,
            plan.features,
            symbol=symbol,
            side=direction,
            strategy_setup=plan.setup_type,
        )

        save_entry_snapshot(snapshot)