from collections.abc import Mapping

from jinja2 import Environment, StrictUndefined


class JinjaTemplateRenderer:
    def __init__(self) -> None:
        self._environment = Environment(undefined=StrictUndefined, autoescape=False)

    def render(self, template: str, variables: Mapping[str, object]) -> str:
        return self._environment.from_string(template).render(**variables)
