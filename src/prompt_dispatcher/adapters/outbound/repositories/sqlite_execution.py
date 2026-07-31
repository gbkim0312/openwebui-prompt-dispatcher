import sqlite3
from datetime import datetime
from pathlib import Path

from prompt_dispatcher.domain.delivery import DeliveryResult
from prompt_dispatcher.domain.enums import ExecutionStatus
from prompt_dispatcher.domain.errors import RepositoryError
from prompt_dispatcher.domain.execution import Execution, ExecutionResult


class SqliteExecutionRepository:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    def _initialize(self) -> None:
        with self._connect() as c:
            c.executescript(
                """CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, job_name TEXT NOT NULL, source_file TEXT, enabled INTEGER NOT NULL, last_loaded_at TEXT, config_hash TEXT); CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, scheduled_time TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, response_length INTEGER, error_type TEXT, error_message TEXT, UNIQUE(job_id, scheduled_time)); CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, execution_id TEXT NOT NULL, channel_type TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, external_id TEXT, error_type TEXT, error_message TEXT);"""
            )

    def try_start(self, execution: Execution) -> bool:
        try:
            with self._connect() as c:
                c.execute(
                    "INSERT INTO executions(id,job_id,scheduled_time,started_at,status) VALUES(?,?,?,?,?)",
                    (
                        execution.id,
                        execution.job_id,
                        execution.scheduled_time.isoformat(),
                        execution.started_at.isoformat(),
                        ExecutionStatus.RUNNING.value,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False
        except sqlite3.Error as exc:
            raise RepositoryError("Unable to start execution") from exc

    def complete(self, execution_id: str, result: ExecutionResult) -> None:
        with self._connect() as c:
            c.execute(
                "UPDATE executions SET status=?, finished_at=?, response_length=?, error_type=?, error_message=? WHERE id=?",
                (
                    result.status.value,
                    result.finished_at.isoformat(),
                    result.response_length,
                    result.error_type,
                    result.error_message,
                    execution_id,
                ),
            )

    def add_delivery(self, execution_id: str, result: DeliveryResult) -> None:
        with self._connect() as c:
            c.execute(
                "INSERT INTO deliveries(execution_id,channel_type,target,status,started_at,finished_at,external_id,error_type,error_message) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    execution_id,
                    result.channel_type,
                    result.target,
                    result.status.value,
                    result.started_at.isoformat(),
                    result.finished_at.isoformat(),
                    result.external_id,
                    result.error_type,
                    result.error_message,
                ),
            )

    def find_running(self, job_id: str) -> Execution | None:
        with self._connect() as c:
            row = c.execute(
                "SELECT id,scheduled_time,started_at FROM executions WHERE job_id=? AND status=? LIMIT 1",
                (job_id, ExecutionStatus.RUNNING.value),
            ).fetchone()
        return (
            Execution(
                row[0], job_id, datetime.fromisoformat(row[1]), datetime.fromisoformat(row[2])
            )
            if row
            else None
        )

    def recover_abandoned(self, older_than: datetime) -> int:
        with self._connect() as c:
            cursor = c.execute(
                "UPDATE executions SET status=?,finished_at=? WHERE status=? AND started_at < ?",
                (
                    ExecutionStatus.ABANDONED.value,
                    older_than.isoformat(),
                    ExecutionStatus.RUNNING.value,
                    older_than.isoformat(),
                ),
            )
            return cursor.rowcount
