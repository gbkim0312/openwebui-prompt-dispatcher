from datetime import UTC, datetime

from prompt_dispatcher.adapters.outbound.repositories.sqlite_execution import (
    SqliteExecutionRepository,
)
from prompt_dispatcher.domain.enums import ExecutionStatus
from prompt_dispatcher.domain.execution import Execution, ExecutionResult


def test_sqlite_rejects_duplicate_scheduled_execution(tmp_path) -> None:
    repository = SqliteExecutionRepository(tmp_path / "db.sqlite")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert repository.try_start(Execution("one", "job", now, now))
    assert not repository.try_start(Execution("two", "job", now, now))


def test_sqlite_stores_and_searches_execution_response(tmp_path) -> None:
    repository = SqliteExecutionRepository(tmp_path / "db.sqlite")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert repository.try_start(Execution("one", "news", now, now))
    repository.complete(
        "one", ExecutionResult(ExecutionStatus.SUCCESS, now, 12, response_content="AI 뉴스 요약")
    )

    history = repository.find_history(now, "AI")

    assert len(history) == 1
    assert history[0].response_content == "AI 뉴스 요약"
    assert repository.get_history("one") == history[0]


def test_sqlite_recovers_running_execution_after_service_restart(tmp_path) -> None:
    repository = SqliteExecutionRepository(tmp_path / "db.sqlite")
    started = datetime(2026, 1, 1, tzinfo=UTC)
    assert repository.try_start(Execution("one", "news", started, started))

    assert repository.recover_abandoned(datetime(2026, 1, 1, 0, 1, tzinfo=UTC)) == 1

    record = repository.get_history("one")
    assert record is not None
    assert record.status == ExecutionStatus.ABANDONED
    assert repository.find_running("news") is None


def test_sqlite_can_manually_release_a_job_execution_lock(tmp_path) -> None:
    repository = SqliteExecutionRepository(tmp_path / "db.sqlite")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert repository.try_start(Execution("one", "news", now, now))

    assert repository.abandon_running("news", now) == 1
    assert repository.find_running("news") is None
    assert repository.get_history("one").status == ExecutionStatus.ABANDONED  # type: ignore[union-attr]
