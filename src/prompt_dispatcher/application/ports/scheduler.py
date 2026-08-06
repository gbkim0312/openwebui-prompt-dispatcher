from collections.abc import Callable
from typing import Protocol

from prompt_dispatcher.domain.job import Job, Schedule


class SchedulerPort(Protocol):
    def register(
        self,
        job: Job,
        callback: Callable[[str], None],
        schedule: Schedule | None = None,
        schedule_id: str | None = None,
    ) -> None: ...
    def start(self) -> None: ...

    def clear(self) -> None: ...
    def shutdown(self) -> None: ...
    @property
    def running(self) -> bool: ...
