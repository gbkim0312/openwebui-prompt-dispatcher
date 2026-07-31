from datetime import timedelta

from prompt_dispatcher.application.ports.clock import ClockPort
from prompt_dispatcher.application.ports.execution_repository import ExecutionRepositoryPort


class RecoverAbandonedExecutions:
    def __init__(self, repository: ExecutionRepositoryPort, clock: ClockPort) -> None:
        self._repository, self._clock = repository, clock

    def execute(self, timezone: str = "UTC", older_than_seconds: int = 3600) -> int:
        return self._repository.recover_abandoned(
            self._clock.now(timezone) - timedelta(seconds=older_than_seconds)
        )
