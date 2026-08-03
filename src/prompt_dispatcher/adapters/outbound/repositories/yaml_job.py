from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from apscheduler.triggers.cron import CronTrigger

from prompt_dispatcher.domain.errors import JobValidationError
from prompt_dispatcher.domain.job import (
    ChannelDestination,
    ExecutionPolicy,
    Job,
    OpenWebUiOptions,
    PromptDefinition,
    ResearchTask,
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
        schedule, prompt, delivery, execution, webui, research = (
            raw.get("schedule", {}),
            raw.get("prompt", {}),
            raw.get("delivery", {}),
            raw.get("execution", {}),
            raw.get("openwebui", {}),
            raw.get("research", {}),
        )
        cron = str(schedule.get("cron", ""))
        fields = cron.split()
        if len(fields) != 5:
            raise JobValidationError("cron must have 5 fields")
        try:
            ZoneInfo(schedule.get("timezone", ""))
        except Exception as exc:
            raise JobValidationError("timezone must be valid IANA name") from exc
        try:
            CronTrigger.from_crontab(cron, timezone=schedule["timezone"])
        except (KeyError, TypeError, ValueError) as exc:
            raise JobValidationError(f"invalid cron expression: {exc}") from exc
        if bool(prompt.get("file")) == bool(prompt.get("text")):
            raise JobValidationError("prompt requires exactly one of file or text")
        channels = delivery.get("channels", [])
        if not channels:
            raise JobValidationError("at least one channel is required")
        if not raw.get("id") or not webui.get("model"):
            raise JobValidationError("id and openwebui.model are required")
        search_range = webui.get("web_search_time_range")
        if search_range is not None and search_range not in {"day", "week", "month", "year"}:
            raise JobValidationError("web_search_time_range must be day, week, month, or year")
        topic = str(webui.get("web_search_topic", "news"))
        depth = str(webui.get("web_search_depth", "basic"))
        max_results = int(webui.get("web_search_max_results", 8))
        if topic not in {"general", "news", "finance"}:
            raise JobValidationError("web_search_topic must be general, news, or finance")
        if depth not in {"basic", "fast", "advanced", "ultra-fast"}:
            raise JobValidationError("web_search_depth is invalid")
        if not 1 <= max_results <= 20:
            raise JobValidationError("web_search_max_results must be between 1 and 20")
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
                search_range,
                webui.get("web_search_query"),
                topic,
                depth,
                max_results,
                tuple(webui.get("web_search_include_domains", [])),
                tuple(webui.get("web_search_exclude_domains", [])),
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
            tuple(self._map_research_task(item) for item in research.get("tasks", [])),
            bool(research.get("use_parent_model", True)),
        )

    @staticmethod
    def _map_research_task(raw: object) -> ResearchTask:
        if not isinstance(raw, dict):
            raise JobValidationError("research.tasks must contain objects")
        task_id = str(raw.get("id", ""))
        if not task_id or not task_id.replace("_", "").replace("-", "").isalnum():
            raise JobValidationError(
                "research task id may use letters, numbers, hyphens, and underscores only"
            )
        query = str(raw.get("query", ""))
        if not query:
            raise JobValidationError("research task query is required")
        time_range = str(raw.get("time_range", "day"))
        topic = str(raw.get("topic", "news"))
        depth = str(raw.get("search_depth", "basic"))
        max_results = int(raw.get("max_results", 5))
        if time_range not in {"day", "week", "month", "year"}:
            raise JobValidationError("research task time_range is invalid")
        if topic not in {"general", "news", "finance"}:
            raise JobValidationError("research task topic is invalid")
        if depth not in {"basic", "fast", "advanced", "ultra-fast"}:
            raise JobValidationError("research task search_depth is invalid")
        if not 1 <= max_results <= 20:
            raise JobValidationError("research task max_results must be between 1 and 20")
        return ResearchTask(
            task_id,
            str(raw.get("name") or task_id),
            query,
            str(raw.get("summary_prompt", "")),
            time_range,
            topic,
            depth,
            max_results,
            tuple(str(value) for value in raw.get("include_domains", [])),
            tuple(str(value) for value in raw.get("exclude_domains", [])),
            str(raw["model"]) if raw.get("model") else None,
        )

    def find_all(self) -> list[Job]:
        return list(self._jobs)

    def find_by_id(self, job_id: str) -> Job | None:
        return next((job for job in self._jobs if job.id == job_id), None)
