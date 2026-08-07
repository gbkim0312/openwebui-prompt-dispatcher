from typing import Protocol

from prompt_dispatcher.domain.job import JobCollectorSource


class JobCollectorPort(Protocol):
    def fetch(self, source: JobCollectorSource) -> str: ...
