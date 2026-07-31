from typing import Protocol

from prompt_dispatcher.domain.job import PromptDefinition


class PromptLoaderPort(Protocol):
    def load(self, prompt_definition: PromptDefinition) -> str: ...
