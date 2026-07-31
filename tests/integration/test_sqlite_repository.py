from datetime import UTC, datetime

from prompt_dispatcher.adapters.outbound.repositories.sqlite_execution import (
    SqliteExecutionRepository,
)
from prompt_dispatcher.domain.execution import Execution


def test_sqlite_rejects_duplicate_scheduled_execution(tmp_path) -> None:
    repository = SqliteExecutionRepository(tmp_path / "db.sqlite")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert repository.try_start(Execution("one", "job", now, now))
    assert not repository.try_start(Execution("two", "job", now, now))
