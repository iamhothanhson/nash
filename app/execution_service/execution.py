from __future__ import annotations

from execution_service.entry_snapshot import EntrySnapshotService
from execution_service.executor import Executor
from execution_service.models import ExecutionResult
from execution_service.position import PositionService
from order_planner.models import OrderPlan


class ExecutionService:
    def __init__(
        self,
        executor: Executor | None = None,
        entry_snapshot_service: EntrySnapshotService | None = None,
        position_service: PositionService | None = None,
    ) -> None:
        self.executor = executor or Executor()
        self.entry_snapshot_service = (
            entry_snapshot_service or EntrySnapshotService()
        )
        self.position_service = position_service or PositionService()

    def execute(self, plan: OrderPlan) -> ExecutionResult:
        execution = self.executor.execute(plan)

        if execution.status != "placed":
            return execution

        self.entry_snapshot_service.record_entry(
            plan,
            symbol=execution.symbol,
            direction=execution.direction,
        )

        self.position_service.record_position(
            plan=plan,
            execution=execution,
        )

        return execution
