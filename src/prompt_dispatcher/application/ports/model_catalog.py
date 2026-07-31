from typing import Protocol


class ModelCatalogPort(Protocol):
    def list_models(self) -> tuple[str, ...]: ...

    def refresh(self) -> bool: ...

    @property
    def revision(self) -> str: ...
