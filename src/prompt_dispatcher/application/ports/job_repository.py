from collections.abc import Sequence
from typing import Protocol

from prompt_dispatcher.domain.job import Job


class JobRepositoryPort(Protocol):
    def find_all(self) -> Sequence[Job]: ...
    def find_by_id(self, job_id: str) -> Job | None: ...
