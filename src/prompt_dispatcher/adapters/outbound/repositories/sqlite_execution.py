import sqlite3
from datetime import datetime
from pathlib import Path
from typing import cast

from prompt_dispatcher.domain.delivery import DeliveryResult
from prompt_dispatcher.domain.enums import ExecutionStatus
from prompt_dispatcher.domain.errors import RepositoryError
from prompt_dispatcher.domain.execution import Execution, ExecutionHistory, ExecutionResult


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
                """CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, job_name TEXT NOT NULL, source_file TEXT, enabled INTEGER NOT NULL, last_loaded_at TEXT, config_hash TEXT); CREATE TABLE IF NOT EXISTS executions (id TEXT PRIMARY KEY, job_id TEXT NOT NULL, scheduled_time TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, response_length INTEGER, error_type TEXT, error_message TEXT, response_content TEXT, UNIQUE(job_id, scheduled_time)); CREATE TABLE IF NOT EXISTS deliveries (id INTEGER PRIMARY KEY, execution_id TEXT NOT NULL, channel_type TEXT NOT NULL, target TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT NOT NULL, external_id TEXT, error_type TEXT, error_message TEXT);"""
            )
            columns = {row[1] for row in c.execute("PRAGMA table_info(executions)")}
            if "response_content" not in columns:
                c.execute("ALTER TABLE executions ADD COLUMN response_content TEXT")

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
                "UPDATE executions SET status=?, finished_at=?, response_length=?, error_type=?, error_message=?, response_content=? WHERE id=?",
                (
                    result.status.value,
                    result.finished_at.isoformat(),
                    result.response_length,
                    result.error_type,
                    result.error_message,
                    result.response_content,
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

    def abandon_running(self, job_id: str, finished_at: datetime) -> int:
        with self._connect() as c:
            cursor = c.execute(
                "UPDATE executions SET status=?,finished_at=?,error_type=?,error_message=? "
                "WHERE job_id=? AND status=?",
                (
                    ExecutionStatus.ABANDONED.value,
                    finished_at.isoformat(),
                    "ManualUnlock",
                    "Execution lock manually released from Web UI",
                    job_id,
                    ExecutionStatus.RUNNING.value,
                ),
            )
            return cursor.rowcount

    def purge_before(self, older_than: datetime) -> int:
        try:
            with self._connect() as c:
                ids = [
                    row[0]
                    for row in c.execute(
                        "SELECT id FROM executions WHERE started_at < ?", (older_than.isoformat(),)
                    )
                ]
                if not ids:
                    return 0
                placeholders = ",".join("?" for _ in ids)
                c.execute(f"DELETE FROM deliveries WHERE execution_id IN ({placeholders})", ids)
                c.execute(f"DELETE FROM executions WHERE id IN ({placeholders})", ids)
                return len(ids)
        except sqlite3.Error as exc:
            raise RepositoryError("Unable to purge execution history") from exc

    @staticmethod
    def _history(row: tuple[object, ...]) -> ExecutionHistory:
        return ExecutionHistory(
            str(row[0]),
            str(row[1]),
            datetime.fromisoformat(str(row[2])),
            datetime.fromisoformat(str(row[3])),
            datetime.fromisoformat(str(row[4])) if row[4] else None,
            ExecutionStatus(str(row[5])),
            int(cast(int | str, row[6])) if row[6] is not None else None,
            str(row[7]) if row[7] else None,
            str(row[8]) if row[8] else None,
            str(row[9]) if row[9] is not None else None,
        )

    def find_history(
        self, since: datetime, query: str = "", limit: int = 100
    ) -> tuple[ExecutionHistory, ...]:
        pattern = f"%{query}%"
        with self._connect() as c:
            rows = c.execute(
                "SELECT id,job_id,scheduled_time,started_at,finished_at,status,response_length,error_type,error_message,response_content "
                "FROM executions WHERE started_at >= ? AND (job_id LIKE ? OR response_content LIKE ? OR error_message LIKE ?) "
                "ORDER BY started_at DESC LIMIT ?",
                (since.isoformat(), pattern, pattern, pattern, limit),
            ).fetchall()
        return tuple(self._history(row) for row in rows)

    def get_history(self, execution_id: str) -> ExecutionHistory | None:
        with self._connect() as c:
            row = c.execute(
                "SELECT id,job_id,scheduled_time,started_at,finished_at,status,response_length,error_type,error_message,response_content "
                "FROM executions WHERE id=?",
                (execution_id,),
            ).fetchone()
        return self._history(row) if row else None
