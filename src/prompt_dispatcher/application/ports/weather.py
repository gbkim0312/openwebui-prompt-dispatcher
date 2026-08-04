from typing import Protocol

from prompt_dispatcher.domain.job import WeatherSource


class WeatherPort(Protocol):
    def fetch(self, source: WeatherSource) -> str: ...
