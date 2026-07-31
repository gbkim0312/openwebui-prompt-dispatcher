from typing import Protocol

from prompt_dispatcher.domain.job import OpenWebUiRequest, OpenWebUiResponse


class OpenWebUiPort(Protocol):
    def generate(self, request: OpenWebUiRequest) -> OpenWebUiResponse: ...
