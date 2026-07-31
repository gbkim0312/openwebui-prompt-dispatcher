from datetime import datetime

from prompt_dispatcher.domain.delivery import DeliveryResult
from prompt_dispatcher.domain.enums import ExecutionStatus
from prompt_dispatcher.domain.execution import Execution, ExecutionResult
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

    def result_for(self, execution_id: str) -> ExecutionResult | None:
        return self._results.get(execution_id)
