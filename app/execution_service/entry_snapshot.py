import time

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
        position_id: str = "",
    ) -> str:
        pid = position_id or str(int(time.time() * 1_000_000))

        snapshot = build_entry_snapshot(
            plan.market_state,
            plan.features,
            symbol=symbol,
            side=direction,
            strategy_setup=plan.setup_type,
            position_id=pid,
            setup_score=plan.setup_score,
        )

        return save_entry_snapshot(snapshot)