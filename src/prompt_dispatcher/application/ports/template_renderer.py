from collections.abc import Mapping
from typing import Protocol


class TemplateRendererPort(Protocol):
    def render(self, template: str, variables: Mapping[str, object]) -> str: ...
