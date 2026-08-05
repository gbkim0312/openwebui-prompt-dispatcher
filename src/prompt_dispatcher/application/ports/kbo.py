from datetime import date
from typing import Protocol

from prompt_dispatcher.domain.job import KboSource


class KboPort(Protocol):
    def fetch(self, source: KboSource, target_date: date) -> str: ...
