from dataclasses import dataclass
from datetime import datetime

from .enums import ExecutionStatus


@dataclass(frozen=True)
class Execution:
    id: str
    job_id: str
    scheduled_time: datetime
    started_at: datetime
    status: ExecutionStatus = ExecutionStatus.RUNNING
    finished_at: datetime | None = None


@dataclass(frozen=True)
class ExecutionResult:
    status: ExecutionStatus
    finished_at: datetime
    response_length: int = 0
    error_type: str | None = None
    error_message: str | None = None
    response_content: str | None = None


@dataclass(frozen=True)
class ExecutionHistory:
    id: str
    job_id: str
    scheduled_time: datetime
    started_at: datetime
    finished_at: datetime | None
    status: ExecutionStatus
    response_length: int | None
    error_type: str | None
    error_message: str | None
    response_content: str | None


def determine_execution_status(successes: int, failures: int) -> ExecutionStatus:
    if failures == 0:
        return ExecutionStatus.SUCCESS
    if successes:
        return ExecutionStatus.PARTIAL_SUCCESS
    return ExecutionStatus.FAILED
