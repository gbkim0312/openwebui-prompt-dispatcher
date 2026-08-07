import re
from datetime import date, datetime
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
    JobCollectorSource,
    WebSearchSource,
    KboSource,
    OpenWebUiOptions,
    PromptDefinition,
    ResearchTask,
    Schedule,
    WeatherSource,
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
        schedule, prompt, delivery, execution, webui, research, context_sources = (
            raw.get("schedule", {}),
            raw.get("prompt", {}),
            raw.get("delivery", {}),
            raw.get("execution", {}),
            raw.get("openwebui", {}),
            raw.get("research", {}),
            raw.get("context_sources", {}),
        )
        cron = str(schedule.get("cron", ""))
        primary_run_at = schedule.get("run_at")
        if cron and primary_run_at:
            raise JobValidationError("schedule cannot contain both cron and run_at")
        try:
            ZoneInfo(schedule.get("timezone", ""))
        except Exception as exc:
            raise JobValidationError("timezone must be valid IANA name") from exc
        if cron:
            if len(cron.split()) != 5:
                raise JobValidationError("cron must have 5 fields")
            try:
                CronTrigger.from_crontab(cron, timezone=schedule["timezone"])
            except (KeyError, TypeError, ValueError) as exc:
                raise JobValidationError(f"invalid cron expression: {exc}") from exc
        elif primary_run_at:
            try:
                parsed_primary = datetime.fromisoformat(str(primary_run_at).replace("Z", "+00:00"))
                if parsed_primary.tzinfo is None:
                    parsed_primary = parsed_primary.replace(tzinfo=ZoneInfo(schedule["timezone"]))
                primary_run_at = parsed_primary.isoformat()
            except (TypeError, ValueError) as exc:
                raise JobValidationError(f"invalid one-time run_at: {exc}") from exc
        else:
            raise JobValidationError("schedule requires cron or run_at")
        if bool(prompt.get("file")) == bool(prompt.get("text")):
            raise JobValidationError("prompt requires exactly one of file or text")
        channels = delivery.get("channels", [])
        if not channels:
            raise JobValidationError("at least one channel is required")
        execution_mode = str(raw.get("execution_mode", "llm"))
        if execution_mode not in {"llm", "direct_message"}:
            raise JobValidationError("execution_mode must be llm or direct_message")
        if not raw.get("id"):
            raise JobValidationError("id is required")
        if execution_mode == "llm" and not webui.get("model"):
            raise JobValidationError("openwebui.model is required for llm jobs")
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
        research_tasks = tuple(self._map_research_task(item) for item in research.get("tasks", []))
        if execution_mode == "direct_message" and research_tasks:
            raise JobValidationError("direct_message jobs cannot contain research tasks")
        task_ids = [task.id for task in research_tasks]
        if len(set(task_ids)) != len(task_ids):
            duplicate_ids = sorted({task_id for task_id in task_ids if task_ids.count(task_id) > 1})
            raise JobValidationError(
                f"research task ids must be unique: {', '.join(duplicate_ids)}"
            )
        primary_schedule = Schedule(cron, schedule["timezone"], primary_run_at, "default")
        schedules = [primary_schedule]
        schedule_ids = {"default"}
        for index, item in enumerate(raw.get("schedules", []) or [], start=1):
            if not isinstance(item, dict):
                raise JobValidationError("schedules entries must be mappings")
            timezone = str(item.get("timezone", schedule["timezone"]))
            try:
                ZoneInfo(timezone)
            except Exception as exc:
                raise JobValidationError("schedule timezone must be valid IANA name") from exc
            schedule_id = str(item.get("id", f"schedule-{index}"))
            if not schedule_id or schedule_id in schedule_ids:
                raise JobValidationError(f"duplicate schedule id: {schedule_id}")
            schedule_ids.add(schedule_id)
            item_cron = str(item.get("cron", "")).strip()
            run_at = item.get("run_at")
            if item_cron and run_at:
                raise JobValidationError("a schedule cannot contain both cron and run_at")
            if item_cron:
                try:
                    CronTrigger.from_crontab(item_cron, timezone=timezone)
                except (TypeError, ValueError) as exc:
                    raise JobValidationError(f"invalid schedule cron expression: {exc}") from exc
                schedules.append(Schedule(item_cron, timezone, id=schedule_id))
            elif run_at:
                try:
                    parsed = datetime.fromisoformat(str(run_at).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
                except (TypeError, ValueError) as exc:
                    raise JobValidationError(f"invalid one-time run_at: {exc}") from exc
                schedules.append(Schedule("", timezone, parsed.isoformat(), schedule_id))
            else:
                raise JobValidationError("additional schedule requires cron or run_at")
        return Job(
            raw["id"],
            raw.get("name", raw["id"]),
            bool(raw.get("enabled", True)),
            primary_schedule,
            OpenWebUiOptions(
                str(webui.get("model", "")),
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
            tuple(schedules[1:]),
            execution_mode,
            ExecutionPolicy(
                int(execution.get("max_instances", 1)),
                bool(execution.get("skip_if_previous_running", True)),
                int(execution.get("misfire_grace_seconds", 300)),
                int(execution.get("retry_count", 0)),
                int(execution.get("retry_delay_seconds", 1)),
            ),
            research_tasks,
            bool(research.get("use_parent_model", True)),
            tuple(self._map_weather_source(item) for item in context_sources.get("weather", [])),
        )

    @staticmethod
    def _map_weather_source(raw: object) -> WeatherSource:
        if not isinstance(raw, dict):
            raise JobValidationError("context_sources.weather must contain objects")
        source_id = str(raw.get("id", ""))
        if not source_id or not source_id.replace("_", "").replace("-", "").isalnum():
            raise JobValidationError("weather source id may use letters, numbers, hyphens, and underscores only")
        try:
            latitude, longitude = float(raw["latitude"]), float(raw["longitude"])
        except (KeyError, TypeError, ValueError) as exc:
            raise JobValidationError("weather source latitude and longitude are required") from exc
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise JobValidationError("weather source latitude or longitude is out of range")
        timezone = str(raw.get("timezone", "Asia/Seoul"))
        try:
            ZoneInfo(timezone)
        except Exception as exc:
            raise JobValidationError("weather source timezone must be valid IANA name") from exc
        days = int(raw.get("forecast_days", 2))
        if not 1 <= days <= 7:
            raise JobValidationError("weather source forecast_days must be between 1 and 7")
        current, daily = bool(raw.get("include_current", True)), bool(raw.get("include_daily", True))
        if not current and not daily:
            raise JobValidationError("weather source must include current or daily forecast")
        return WeatherSource(
            source_id,
            str(raw.get("name") or source_id),
            latitude,
            longitude,
            timezone,
            current,
            daily,
            days,
            bool(raw.get("include_alerts", False)),
            bool(raw.get("include_weekly", False)),
        )

    @staticmethod
    def _map_research_task(raw: object) -> ResearchTask:
        if not isinstance(raw, dict):
            raise JobValidationError("research.tasks must contain objects")
        task_id = str(raw.get("id", ""))
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", task_id):
            raise JobValidationError(
                "research task id must start with a lowercase letter and use lowercase letters, numbers, hyphens, or underscores only"
            )
        query = str(raw.get("query", ""))
        use_web_search = bool(raw.get("use_web_search", True))
        weather_sources = tuple(
            YamlJobRepository._map_weather_source(item) for item in raw.get("weather_sources", [])
        )
        kbo_sources = tuple(
            YamlJobRepository._map_kbo_source(item) for item in raw.get("kbo_sources", [])
        )
        job_collector_sources = tuple(
            YamlJobRepository._map_job_collector_source(item)
            for item in raw.get("job_collector_sources", [])
        )
        web_search_sources = tuple(
            YamlJobRepository._map_web_search_source(item)
            for item in raw.get("web_search_sources", [])
        )
        if use_web_search and not query and not web_search_sources:
            raise JobValidationError("research task query is required when web search is enabled")
        if not use_web_search and not web_search_sources and not weather_sources and not kbo_sources and not job_collector_sources:
            raise JobValidationError(
                "research task must enable web search or add a weather, KBO, or Job Collector source"
            )
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
        days_of_week = tuple(str(value).lower() for value in raw.get("days_of_week", []))
        valid_days = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
        if len(set(days_of_week)) != len(days_of_week) or any(
            day not in valid_days for day in days_of_week
        ):
            raise JobValidationError(
                "research task days_of_week must contain unique values from mon through sun"
            )
        return ResearchTask(
            task_id,
            str(raw.get("name") or task_id),
            query,
            str(raw.get("summary_prompt", "")),
            bool(raw.get("use_prompt", True)),
            time_range,
            topic,
            depth,
            max_results,
            tuple(str(value) for value in raw.get("include_domains", [])),
            tuple(str(value) for value in raw.get("exclude_domains", [])),
            str(raw["model"]) if raw.get("model") else None,
            bool(raw.get("enabled", True)),
            days_of_week,
            bool(raw.get("include_raw_content", False)),
            use_web_search,
            weather_sources,
            kbo_sources,
            job_collector_sources,
            web_search_sources,
        )

    @staticmethod
    def _map_web_search_source(raw: object) -> WebSearchSource:
        if not isinstance(raw, dict):
            raise JobValidationError("web_search_sources must contain objects")
        source_id = str(raw.get("id", ""))
        if not source_id or not source_id.replace("_", "").replace("-", "").isalnum():
            raise JobValidationError("Web search source id is invalid")
        time_range = str(raw.get("time_range", "day"))
        topic = str(raw.get("topic", "news"))
        depth = str(raw.get("search_depth", "basic"))
        if time_range not in {"day", "week", "month", "year"}:
            raise JobValidationError("web search source time_range is invalid")
        if topic not in {"general", "news", "finance"}:
            raise JobValidationError("web search source topic is invalid")
        if depth not in {"basic", "fast", "advanced", "ultra-fast"}:
            raise JobValidationError("web search source search_depth is invalid")
        max_results = int(raw.get("max_results", 5))
        if not 1 <= max_results <= 20:
            raise JobValidationError("web search source max_results must be between 1 and 20")
        return WebSearchSource(
            source_id,
            str(raw.get("name") or source_id),
            str(raw["query"]) if raw.get("query") else None,
            time_range,
            topic,
            depth,
            max_results,
            tuple(str(value) for value in raw.get("include_domains", [])),
            tuple(str(value) for value in raw.get("exclude_domains", [])),
            bool(raw.get("include_raw_content", False)),
        )

    @staticmethod
    def _map_job_collector_source(raw: object) -> JobCollectorSource:
        if not isinstance(raw, dict):
            raise JobValidationError("job_collector_sources must contain objects")
        source_id = str(raw.get("id", ""))
        if not source_id or not source_id.replace("_", "").replace("-", "").isalnum():
            raise JobValidationError(
                "Job Collector source id may use letters, numbers, hyphens, and underscores only"
            )
        limit = int(raw.get("limit", 20))
        if not 1 <= limit <= 100:
            raise JobValidationError("Job Collector source limit must be between 1 and 100")
        min_experience = raw.get("min_experience")
        max_experience = raw.get("max_experience")
        try:
            minimum = int(min_experience) if min_experience is not None else None
            maximum = int(max_experience) if max_experience is not None else None
        except (TypeError, ValueError) as exc:
            raise JobValidationError("Job Collector experience values must be integers") from exc
        if (minimum is not None and minimum < 0) or (maximum is not None and maximum < 0):
            raise JobValidationError("Job Collector experience values cannot be negative")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise JobValidationError("Job Collector min_experience cannot exceed max_experience")
        statuses = tuple(str(value).upper() for value in raw.get("statuses", ["ACTIVE"]))
        valid_statuses = {"ACTIVE", "CLOSED", "DELETED", "UNKNOWN"}
        if any(value not in valid_statuses for value in statuses):
            raise JobValidationError("Job Collector statuses are invalid")
        experience_types = tuple(str(value).upper() for value in raw.get("experience_types", []))
        if any(value not in {"NEWBIE", "EXPERIENCED", "ANY", "UNKNOWN"} for value in experience_types):
            raise JobValidationError("Job Collector experience_types are invalid")
        return JobCollectorSource(
            source_id,
            str(raw.get("name") or source_id),
            str(raw["profile_id"]) if raw.get("profile_id") else None,
            str(raw["keyword"]) if raw.get("keyword") else None,
            tuple(str(value) for value in raw.get("sources", [])),
            statuses,
            tuple(str(value) for value in raw.get("categories", [])),
            tuple(str(value) for value in raw.get("skills", [])),
            str(raw["region"]) if raw.get("region") else None,
            tuple(str(value) for value in raw.get("employment_types", [])),
            experience_types,
            minimum,
            maximum,
            limit,
            str(raw.get("sort", "updated_at:desc")),
        )

    @staticmethod
    def _map_kbo_source(raw: object) -> KboSource:
        if not isinstance(raw, dict):
            raise JobValidationError("kbo_sources must contain objects")
        source_id = str(raw.get("id", ""))
        if not source_id or not source_id.replace("_", "").replace("-", "").isalnum():
            raise JobValidationError("KBO source id may use letters, numbers, hyphens, and underscores only")
        data_type = str(raw.get("data_type", "latest_results"))
        if data_type not in {
            "teams",
            "latest_results",
            "games",
            "rankings",
            "player_stats",
            "awards",
            "game_details",
            "lineups",
            "analysis",
            "starting_pitcher_analysis",
        }:
            raise JobValidationError("KBO source data_type is invalid")
        team = str(raw["team"]).upper() if raw.get("team") else None
        if team and (len(team) > 3 or not team.isalnum()):
            raise JobValidationError("KBO source team code is invalid")
        season = int(raw["season"]) if raw.get("season") else None
        if season and not 1982 <= season <= 2100:
            raise JobValidationError("KBO source season is invalid")
        role = str(raw.get("role", "hitter"))
        if role not in {"hitter", "pitcher"}:
            raise JobValidationError("KBO source role must be hitter or pitcher")
        limit = int(raw.get("limit", 5))
        if not 1 <= limit <= 50:
            raise JobValidationError("KBO source limit must be between 1 and 50")
        game_id = int(raw["game_id"]) if raw.get("game_id") else None
        if data_type in {"game_details", "lineups", "analysis", "starting_pitcher_analysis"} and not (
            game_id or team
        ):
            raise JobValidationError("KBO detail data requires a game_id or team")
        if game_id is not None and game_id < 1:
            raise JobValidationError("KBO source game_id must be positive")
        range_days = int(raw.get("range_days", 1))
        if not 1 <= range_days <= 31:
            raise JobValidationError("KBO source range_days must be between 1 and 31")
        status = str(raw["status"]) if raw.get("status") else None
        if status and status not in {"scheduled", "in_progress", "completed", "cancelled"}:
            raise JobValidationError("KBO source status is invalid")
        league_type = str(raw["league_type"]) if raw.get("league_type") else None
        reference_date = str(raw["reference_date"]) if raw.get("reference_date") else None
        if reference_date:
            try:
                date.fromisoformat(reference_date)
            except ValueError as exc:
                raise JobValidationError("KBO source reference_date must be YYYY-MM-DD") from exc
        return KboSource(
            source_id,
            str(raw.get("name") or source_id),
            data_type,
            team,
            season,
            role,
            limit,
            bool(raw.get("collect_before_fetch", False)),
            game_id,
            range_days,
            status,
            league_type,
            reference_date,
            bool(raw.get("use_today", False)),
        )

    def find_all(self) -> list[Job]:
        return list(self._jobs)

    def find_by_id(self, job_id: str) -> Job | None:
        return next((job for job in self._jobs if job.id == job_id), None)
