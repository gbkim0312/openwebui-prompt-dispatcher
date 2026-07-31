from dataclasses import dataclass

from prompt_dispatcher.domain.enums import ExecutionStatus


@dataclass(frozen=True)
class RunJobResult:
    execution_id: str | None
    status: ExecutionStatus
    message: str | None = None
