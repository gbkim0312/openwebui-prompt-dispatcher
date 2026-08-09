from typing import Protocol

from prompt_dispatcher.domain.job import AirQualitySource


class AirQualityPort(Protocol):
    def fetch(self, source: AirQualitySource) -> str: ...
