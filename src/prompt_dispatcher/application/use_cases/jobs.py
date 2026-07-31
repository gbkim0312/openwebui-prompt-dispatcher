from collections.abc import Sequence

from prompt_dispatcher.application.ports.job_repository import JobRepositoryPort
from prompt_dispatcher.domain.job import Job


class ListJobs:
    def __init__(self, jobs: JobRepositoryPort) -> None:
        self._jobs = jobs

    def execute(self) -> Sequence[Job]:
        return self._jobs.find_all()
