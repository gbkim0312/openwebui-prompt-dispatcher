from pathlib import Path

from prompt_dispatcher.domain.errors import PromptLoadError
from prompt_dispatcher.domain.job import PromptDefinition


class FilePromptLoader:
    def __init__(self, base_directory: Path) -> None:
        self._base = base_directory.resolve()

    def load(self, prompt_definition: PromptDefinition) -> str:
        if prompt_definition.text is not None:
            return prompt_definition.text
        if not prompt_definition.file:
            raise PromptLoadError("Prompt file or text is required")
        path = (self._base / prompt_definition.file).resolve()
        if self._base not in path.parents:
            raise PromptLoadError("Prompt file must be inside prompts directory")
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PromptLoadError("Unable to load prompt file") from exc


class FakePromptLoader:
    def __init__(self, prompts: dict[str, str] | None = None) -> None:
        self.prompts = prompts or {}

    def load(self, prompt_definition: PromptDefinition) -> str:
        if prompt_definition.text is not None:
            return prompt_definition.text
        if prompt_definition.file and prompt_definition.file in self.prompts:
            return self.prompts[prompt_definition.file]
        raise PromptLoadError("Fake prompt not found")
