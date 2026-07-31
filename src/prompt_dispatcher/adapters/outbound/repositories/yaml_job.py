from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

from prompt_dispatcher.domain.errors import JobValidationError
from prompt_dispatcher.domain.job import (
    ChannelDestination,
    ExecutionPolicy,
    Job,
    OpenWebUiOptions,
    PromptDefinition,
    Schedule,
)


class YamlJobRepository:
    def __init__(self, directory: Path) -> None:
        self._directory = directory
        self.errors: list[str] = []
        self._jobs: list[Job] = []
        self.reload()

    def reload(self) -> None:
        self.errors, self._jobs = [], []
        seen: set[str] = set()
        for path in sorted(self._directory.glob("*.job.yaml")):
            try:
                job = self._map(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
                if job.id in seen:
                    raise JobValidationError(f"Duplicate job id: {job.id}")
                seen.add(job.id)
                self._jobs.append(job)
            except Exception as exc:
                self.errors.append(f"{path.name}: {exc}")

    def _map(self, raw: dict[str, Any]) -> Job:
        if raw.get("version") != 1:
            raise JobValidationError("version must be 1")
        schedule, prompt, delivery, execution, webui = (
            raw.get("schedule", {}),
            raw.get("prompt", {}),
            raw.get("delivery", {}),
            raw.get("execution", {}),
            raw.get("openwebui", {}),
        )
        cron = str(schedule.get("cron", ""))
        fields = cron.split()
        if len(fields) != 5:
            raise JobValidationError("cron must have 5 fields")
        try:
            ZoneInfo(schedule.get("timezone", ""))
        except Exception as exc:
            raise JobValidationError("timezone must be valid IANA name") from exc
        if bool(prompt.get("file")) == bool(prompt.get("text")):
            raise JobValidationError("prompt requires exactly one of file or text")
        channels = delivery.get("channels", [])
        if not channels:
            raise JobValidationError("at least one channel is required")
        if not raw.get("id") or not webui.get("model"):
            raise JobValidationError("id and openwebui.model are required")
        return Job(
            raw["id"],
            raw.get("name", raw["id"]),
            bool(raw.get("enabled", True)),
            Schedule(cron, schedule["timezone"]),
            OpenWebUiOptions(
                webui["model"],
                tuple(webui.get("skill_ids", [])),
                tuple(webui.get("tool_ids", [])),
                tuple(webui.get("required_tool_ids", [])),
                int(webui.get("timeout_seconds", 600)),
            ),
            PromptDefinition(prompt.get("file"), prompt.get("text"), prompt.get("variables", {})),
            tuple(
                ChannelDestination(item["type"], item["target"], item.get("options", {}))
                for item in channels
            ),
            ExecutionPolicy(
                int(execution.get("max_instances", 1)),
                bool(execution.get("skip_if_previous_running", True)),
                int(execution.get("misfire_grace_seconds", 300)),
                int(execution.get("retry_count", 0)),
                int(execution.get("retry_delay_seconds", 1)),
            ),
        )

    def find_all(self) -> list[Job]:
        return list(self._jobs)

    def find_by_id(self, job_id: str) -> Job | None:
        return next((job for job in self._jobs if job.id == job_id), None)
