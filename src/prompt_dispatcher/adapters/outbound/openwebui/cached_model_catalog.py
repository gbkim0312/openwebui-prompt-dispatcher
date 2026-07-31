import hashlib
import json
import os
import tempfile
from pathlib import Path
from threading import Lock
from typing import Protocol


class ModelSourcePort(Protocol):
    def list_models(self) -> tuple[str, ...]: ...


class CachedModelCatalog:
    """Persistent cache that keeps UI reads fast and refreshes against Open WebUI on demand."""

    def __init__(self, source: ModelSourcePort, path: Path) -> None:
        self._source, self._path, self._lock = source, path, Lock()
        self._models: tuple[str, ...] = ()
        self._revision = ""
        self._read_cache()

    @property
    def revision(self) -> str:
        return self._revision

    def _read_cache(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            models = payload.get("models", [])
            if isinstance(models, list) and all(isinstance(model, str) for model in models):
                self._models = tuple(models)
                self._revision = str(payload.get("revision", self._hash(self._models)))
        except (OSError, ValueError, TypeError):
            return

    @staticmethod
    def _hash(models: tuple[str, ...]) -> str:
        return hashlib.sha256("\n".join(models).encode()).hexdigest()[:16]

    def _write_cache(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=self._path.parent, prefix=".models-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(
                {"revision": self._revision, "models": self._models}, file, ensure_ascii=False
            )
        Path(temporary).replace(self._path)

    def list_models(self) -> tuple[str, ...]:
        if not self._models:
            self.refresh()
        return self._models

    def refresh(self) -> bool:
        models = tuple(sorted(set(self._source.list_models())))
        revision = self._hash(models)
        with self._lock:
            if revision == self._revision:
                return False
            self._models, self._revision = models, revision
            self._write_cache()
            return True
