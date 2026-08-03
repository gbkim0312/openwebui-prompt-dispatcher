from datetime import datetime

from prompt_dispatcher.domain.delivery import DeliveryResult
from prompt_dispatcher.domain.enums import ExecutionStatus
from prompt_dispatcher.domain.execution import Execution, ExecutionHistory, ExecutionResult
from prompt_dispatcher.domain.job import Job


class InMemoryJobRepository:
    def __init__(self, jobs: list[Job] | tuple[Job, ...] = ()) -> None:
        self.jobs = list(jobs)

    def find_all(self) -> list[Job]:
        return list(self.jobs)

    def find_by_id(self, job_id: str) -> Job | None:
        return next((job for job in self.jobs if job.id == job_id), None)


class InMemoryExecutionRepository:
    def __init__(self) -> None:
        self.executions: list[Execution] = []
        self.deliveries: dict[str, list[DeliveryResult]] = {}
        self._results: dict[str, ExecutionResult] = {}

    def try_start(self, execution: Execution) -> bool:
        if any(
            item.job_id == execution.job_id and item.scheduled_time == execution.scheduled_time
            for item in self.executions
        ):
            return False
        self.executions.append(execution)
        return True

    def complete(self, execution_id: str, result: ExecutionResult) -> None:
        self._results[execution_id] = result

    def add_delivery(self, execution_id: str, result: DeliveryResult) -> None:
        self.deliveries.setdefault(execution_id, []).append(result)

    def find_running(self, job_id: str) -> Execution | None:
        return next(
            (
                item
                for item in self.executions
                if item.job_id == job_id and item.id not in self._results
            ),
            None,
        )

    def recover_abandoned(self, older_than: datetime) -> int:
        count = 0
        for execution in self.executions:
            if execution.id not in self._results and execution.started_at < older_than:
                self._results[execution.id] = ExecutionResult(ExecutionStatus.ABANDONED, older_than)
                count += 1
        return count

    def abandon_running(self, job_id: str, finished_at: datetime) -> int:
        count = 0
        for execution in self.executions:
            if execution.job_id == job_id and execution.id not in self._results:
                self._results[execution.id] = ExecutionResult(
                    ExecutionStatus.ABANDONED,
                    finished_at,
                    error_type="ManualUnlock",
                    error_message="Execution lock manually released from Web UI",
                )
                count += 1
        return count

    def purge_before(self, older_than: datetime) -> int:
        obsolete = [item.id for item in self.executions if item.started_at < older_than]
        self.executions = [item for item in self.executions if item.id not in obsolete]
        for execution_id in obsolete:
            self._results.pop(execution_id, None)
            self.deliveries.pop(execution_id, None)
        return len(obsolete)

    def find_history(
        self, since: datetime, query: str = "", limit: int = 100
    ) -> tuple[ExecutionHistory, ...]:
        records = [
            self.get_history(item.id)
            for item in self.executions
            if item.started_at >= since and query in (item.job_id + (self._results.get(item.id, ExecutionResult(ExecutionStatus.RUNNING, item.started_at)).response_content or ""))
        ]
        return tuple(record for record in records if record is not None)[:limit]

    def get_history(self, execution_id: str) -> ExecutionHistory | None:
        execution = next((item for item in self.executions if item.id == execution_id), None)
        if execution is None:
            return None
        result = self._results.get(execution_id)
        return ExecutionHistory(
            execution.id,
            execution.job_id,
            execution.scheduled_time,
            execution.started_at,
            result.finished_at if result else None,
            result.status if result else ExecutionStatus.RUNNING,
            result.response_length if result else None,
            result.error_type if result else None,
            result.error_message if result else None,
            result.response_content if result else None,
        )

    def result_for(self, execution_id: str) -> ExecutionResult | None:
        return self._results.get(execution_id)
