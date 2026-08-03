import logging
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from prompt_dispatcher.adapters.outbound.channels.nextcloud_talk import NextcloudTalkChannel
from prompt_dispatcher.adapters.outbound.channels.smtp_email import SmtpEmailChannel
from prompt_dispatcher.adapters.outbound.channels.telegram import TelegramChannel
from prompt_dispatcher.adapters.outbound.repositories.web_management import WebManagementStore
from prompt_dispatcher.application.dto.commands import RunJobCommand
from prompt_dispatcher.application.use_cases.send_prompt import SendPromptCommand
from prompt_dispatcher.bootstrap.container import ApplicationContainer
from prompt_dispatcher.bootstrap.settings import Settings
from prompt_dispatcher.domain.delivery import DeliveryResult, OutboundMessage
from prompt_dispatcher.domain.enums import DeliveryStatus
from prompt_dispatcher.domain.job import ChannelDestination

logger = logging.getLogger(__name__)


class JobPayload(BaseModel):
    document: dict[str, Any]
    prompt: str = ""


class SecretPayload(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


class InstantPromptPayload(BaseModel):
    prompt: str
    model: str
    title: str = "즉시 프롬프트"
    skill_ids: list[str] = Field(default_factory=list)
    tool_ids: list[str] = Field(default_factory=list)
    timeout_seconds: int = Field(default=600, gt=0)
    web_search_time_range: Literal["day", "week", "month", "year"] | None = None
    web_search_query: str | None = None
    web_search_topic: Literal["general", "news", "finance"] = "news"
    web_search_depth: Literal["basic", "fast", "advanced", "ultra-fast"] = "basic"
    web_search_max_results: int = Field(default=8, ge=1, le=20)
    web_search_include_domains: list[str] = Field(default_factory=list)
    web_search_exclude_domains: list[str] = Field(default_factory=list)
    channels: list[dict[str, str]] = Field(default_factory=list)
    dry_run: bool = False


class RedispatchPayload(BaseModel):
    channels: list[dict[str, str]] = Field(default_factory=list)


def create_app(container: ApplicationContainer) -> FastAPI:
    app = FastAPI(title="prompt-dispatcher")
    static = Path(__file__).parent / "static" / "index.html"
    store = WebManagementStore(
        container.settings.jobs_directory,
        container.settings.prompts_directory,
        container.settings.database_path.parent / "management.env",
    )

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static)

    @app.get("/health")
    def health() -> dict[str, object]:
        jobs = container.list_jobs.execute()
        return {
            "status": "ok",
            "scheduler_running": container.scheduler.running,
            "loaded_jobs": len(jobs),
            "enabled_jobs": sum(job.enabled for job in jobs),
        }

    @app.get("/ready")
    def ready() -> dict[str, str]:
        if container.jobs.errors:
            raise HTTPException(503, "Job configuration errors")
        return {"status": "ready"}

    @app.get("/api/jobs")
    def list_jobs() -> list[dict[str, object]]:
        return [
            {
                "id": job.id,
                "name": job.name,
                "enabled": job.enabled,
                "cron": job.schedule.cron,
                "timezone": job.schedule.timezone,
                "channels": [destination.channel_type for destination in job.destinations],
            }
            for job in container.list_jobs.execute()
        ]

    @app.get("/api/channels")
    def channels() -> list[dict[str, str]]:
        destinations = {
            (destination.channel_type, destination.target)
            for job in container.list_jobs.execute()
            for destination in job.destinations
        }
        values = store.read_values()
        if values.get("TELEGRAM_PERSONAL_BOT_TOKEN") and values.get("TELEGRAM_PERSONAL_CHAT_ID"):
            destinations.add(("telegram", "personal"))
        if all(
            values.get(key)
            for key in (
                "NEXTCLOUD_TALK_PERSONAL_USERNAME",
                "NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD",
                "NEXTCLOUD_TALK_PERSONAL_ROOM_TOKEN",
            )
        ):
            destinations.add(("nextcloud_talk", "personal"))
        if all(values.get(key) for key in ("SMTP_USERNAME", "SMTP_PASSWORD", "SMTP_PERSONAL_TO")):
            destinations.add(("email", "personal"))
        return [
            {"type": channel_type, "target": target}
            for channel_type, target in sorted(destinations)
            if channel_type != "fake"
        ]

    @app.get("/api/models")
    def models() -> dict[str, object]:
        try:
            return {
                "models": container.model_catalog.list_models(),
                "revision": container.model_catalog.revision,
            }
        except Exception as error:
            raise HTTPException(502, "Open WebUI 모델 목록을 불러올 수 없습니다.") from error

    @app.post("/api/models/refresh")
    def refresh_models() -> dict[str, object]:
        try:
            changed = container.model_catalog.refresh()
            return {
                "changed": changed,
                "models": container.model_catalog.list_models(),
                "revision": container.model_catalog.revision,
            }
        except Exception as error:
            raise HTTPException(502, "Open WebUI 모델 목록을 갱신할 수 없습니다.") from error

    @app.get("/api/capabilities")
    def capabilities() -> dict[str, object]:
        return {
            capability_type: list(items)
            for capability_type, items in container.capability_catalog.list_capabilities().items()
        }

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, object]:
        job = container.jobs.find_by_id(job_id)
        if job is None:
            raise HTTPException(404, "Job not found")
        return {
            "document": {
                "version": 1,
                "id": job.id,
                "name": job.name,
                "enabled": job.enabled,
                "schedule": {"cron": job.schedule.cron, "timezone": job.schedule.timezone},
                "openwebui": {
                    "model": job.openwebui_options.model,
                    "skill_ids": list(job.openwebui_options.skill_ids),
                    "tool_ids": list(job.openwebui_options.tool_ids),
                    "required_tool_ids": list(job.openwebui_options.required_tool_ids),
                    "timeout_seconds": job.openwebui_options.timeout_seconds,
                    "web_search_time_range": job.openwebui_options.web_search_time_range,
                    "web_search_query": job.openwebui_options.web_search_query,
                    "web_search_topic": job.openwebui_options.web_search_topic,
                    "web_search_depth": job.openwebui_options.web_search_depth,
                    "web_search_max_results": job.openwebui_options.web_search_max_results,
                    "web_search_include_domains": list(
                        job.openwebui_options.web_search_include_domains
                    ),
                    "web_search_exclude_domains": list(
                        job.openwebui_options.web_search_exclude_domains
                    ),
                },
                "prompt": {"variables": dict(job.prompt_definition.variables)},
                "delivery": {
                    "channels": [
                        {"type": destination.channel_type, "target": destination.target}
                        for destination in job.destinations
                    ]
                },
                "execution": {
                    "max_instances": job.execution_policy.max_instances,
                    "skip_if_previous_running": job.execution_policy.skip_if_previous_running,
                    "misfire_grace_seconds": job.execution_policy.misfire_grace_seconds,
                    "retry_count": job.execution_policy.retry_count,
                    "retry_delay_seconds": job.execution_policy.retry_delay_seconds,
                },
                "research": {
                    "tasks": [
                        {
                            "id": task.id,
                            "name": task.name,
                            "query": task.query,
                            "summary_prompt": task.summary_prompt,
                            "time_range": task.time_range,
                            "topic": task.topic,
                            "search_depth": task.search_depth,
                            "max_results": task.max_results,
                            "include_domains": list(task.include_domains),
                            "exclude_domains": list(task.exclude_domains),
                            "model": task.model,
                            "enabled": task.enabled,
                            "days_of_week": list(task.days_of_week),
                        }
                        for task in job.research_tasks
                    ],
                    "use_parent_model": job.research_use_parent_model,
                },
            },
            "prompt": store.read_prompt(job_id),
        }

    @app.put("/api/jobs/{job_id}")
    def save_job(job_id: str, payload: JobPayload) -> dict[str, str]:
        try:
            store.save_job(job_id, payload.document, payload.prompt)
            container.jobs.reload()
            matching_errors = [
                error for error in container.jobs.errors if error.startswith(f"{job_id}.job.yaml:")
            ]
            if matching_errors:
                raise ValueError(matching_errors[0])
            container.register_schedules.execute()
        except Exception as error:
            raise HTTPException(422, str(error)) from error
        return {"status": "saved"}

    @app.delete("/api/jobs/{job_id}")
    def delete_job(job_id: str) -> dict[str, str]:
        store.delete_job(job_id)
        container.jobs.reload()
        container.register_schedules.execute()
        return {"status": "deleted"}

    @app.post("/api/jobs/{job_id}/run")
    def run_job(
        job_id: str,
        dry_run: bool = False,
        skip_openwebui: bool = False,
        allow_disabled: bool = False,
    ) -> dict[str, str | None]:
        try:
            result = container.run_job.execute(
                RunJobCommand(
                    job_id,
                    dry_run=dry_run,
                    skip_openwebui=skip_openwebui,
                    allow_disabled=allow_disabled,
                )
            )
        except Exception as error:
            logger.exception("event=job_run_api_failed job_id=%s", job_id)
            raise HTTPException(500, str(error)) from error
        return {
            "status": result.status,
            "execution_id": result.execution_id,
            "message": result.message,
        }

    @app.post("/api/prompt/send")
    def send_prompt(payload: InstantPromptPayload) -> dict[str, object]:
        try:
            destinations = tuple(
                ChannelDestination(channel["type"], channel["target"])
                for channel in payload.channels
                if channel.get("type") and channel.get("target")
            )
            result = container.send_prompt.execute(
                SendPromptCommand(
                    prompt=payload.prompt,
                    model=payload.model,
                    title=payload.title,
                    destinations=destinations,
                    skill_ids=tuple(payload.skill_ids),
                    tool_ids=tuple(payload.tool_ids),
                    timeout_seconds=payload.timeout_seconds,
                    dry_run=payload.dry_run,
                    web_search_time_range=payload.web_search_time_range,
                    web_search_query=payload.web_search_query,
                    web_search_topic=payload.web_search_topic,
                    web_search_depth=payload.web_search_depth,
                    web_search_max_results=payload.web_search_max_results,
                    web_search_include_domains=tuple(payload.web_search_include_domains),
                    web_search_exclude_domains=tuple(payload.web_search_exclude_domains),
                )
            )
            return {
                "content": result.content,
                "successful_targets": result.successful_targets,
                "failed_targets": result.failed_targets,
            }
        except Exception as error:
            raise HTTPException(422, str(error)) from error

    @app.get("/api/settings")
    def settings() -> dict[str, object]:
        values = store.read_values()
        return {
            "configured": sorted(key for key, value in values.items() if value),
            "values": values,
            "restart_required": True,
        }

    @app.put("/api/settings")
    def save_settings(payload: SecretPayload) -> dict[str, str]:
        store.save_secrets(payload.values)
        return {"status": "saved", "message": "Restart the service to apply connection settings."}

    @app.post("/api/settings/test/{channel_type}")
    def test_connection(
        channel_type: Literal["telegram", "nextcloud_talk", "email"]
    ) -> dict[str, str]:
        """Send a short real message using the settings currently saved by the UI."""
        values = store.read_values()
        settings = Settings.from_environment()
        message = OutboundMessage("Prompt Dispatcher 연결 테스트", "연결 테스트 메시지입니다.")
        channel: TelegramChannel | NextcloudTalkChannel | SmtpEmailChannel
        try:
            if channel_type == "telegram":
                channel = TelegramChannel(
                    {
                        "personal": (
                            values["TELEGRAM_PERSONAL_BOT_TOKEN"],
                            values["TELEGRAM_PERSONAL_CHAT_ID"],
                        )
                    }
                )
            elif channel_type == "nextcloud_talk":
                channel = NextcloudTalkChannel(
                    values["NEXTCLOUD_URL"],
                    {
                        "personal": (
                            values["NEXTCLOUD_TALK_PERSONAL_USERNAME"],
                            values["NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD"],
                            values["NEXTCLOUD_TALK_PERSONAL_ROOM_TOKEN"],
                        )
                    },
                    settings.nextcloud_verify_tls,
                )
            else:
                channel = SmtpEmailChannel(
                    settings.smtp_host,
                    settings.smtp_port,
                    settings.smtp_username,
                    settings.smtp_password,
                    settings.smtp_from_address,
                    {"personal": tuple(part.strip() for part in values["SMTP_PERSONAL_TO"].split(",") if part.strip())},
                    settings.smtp_use_tls,
                )
            receipt = channel.send("personal", message)
        except Exception as error:
            detail = str(error).replace("\n", " ")
            logger.warning(
                "event=connection_test_failed channel_type=%s error_type=%s error_message=%s",
                channel_type,
                type(error).__name__,
                detail,
            )
            raise HTTPException(422, detail) from error
        logger.info(
            "event=connection_test_success channel_type=%s external_id=%s",
            channel_type,
            receipt.external_id,
        )
        return {"status": "sent", "message": "테스트 메시지를 전송했습니다."}

    @app.get("/api/executions")
    def executions(query: str = "", days: int = 30, limit: int = 100) -> list[dict[str, object]]:
        since = container.clock.now("UTC") - timedelta(days=max(1, min(days, 3650)))
        records = container.executions.find_history(since, query.strip(), max(1, min(limit, 200)))
        return [
            {
                "id": record.id,
                "job_id": record.job_id,
                "scheduled_time": record.scheduled_time.isoformat(),
                "started_at": record.started_at.isoformat(),
                "finished_at": record.finished_at.isoformat() if record.finished_at else None,
                "status": record.status.value,
                "response_length": record.response_length,
                "error_type": record.error_type,
                "error_message": record.error_message,
                "preview": (record.response_content or "")[:500],
            }
            for record in records
        ]

    @app.get("/api/executions/{execution_id}")
    def execution_detail(execution_id: str) -> dict[str, object]:
        record = container.executions.get_history(execution_id)
        if record is None:
            raise HTTPException(404, "Execution not found")
        return {
            "id": record.id,
            "job_id": record.job_id,
            "scheduled_time": record.scheduled_time.isoformat(),
            "started_at": record.started_at.isoformat(),
            "finished_at": record.finished_at.isoformat() if record.finished_at else None,
            "status": record.status.value,
            "response_length": record.response_length,
            "error_type": record.error_type,
            "error_message": record.error_message,
            "content": record.response_content or "",
        }

    @app.post("/api/executions/{execution_id}/dispatch")
    def redispatch_execution(execution_id: str, payload: RedispatchPayload) -> dict[str, object]:
        record = container.executions.get_history(execution_id)
        if record is None:
            raise HTTPException(404, "Execution not found")
        if not record.response_content:
            raise HTTPException(422, "This execution has no stored response to dispatch")
        destinations = tuple(
            ChannelDestination(item.get("type", ""), item.get("target", ""))
            for item in payload.channels
            if item.get("type") and item.get("target")
        )
        if not destinations:
            raise HTTPException(422, "At least one channel is required")
        successes: list[str] = []
        failures: list[str] = []
        for destination in destinations:
            started = container.clock.now("UTC")
            label = f"{destination.channel_type}:{destination.target}"
            try:
                receipt = container.channels.resolve(destination.channel_type).send(
                    destination.target, OutboundMessage(record.job_id, record.response_content)
                )
                container.executions.add_delivery(
                    execution_id,
                    DeliveryResult(
                        destination.channel_type,
                        destination.target,
                        DeliveryStatus.SUCCESS,
                        started,
                        container.clock.now("UTC"),
                        receipt.external_id,
                    ),
                )
                successes.append(label)
            except Exception as error:
                container.executions.add_delivery(
                    execution_id,
                    DeliveryResult(
                        destination.channel_type,
                        destination.target,
                        DeliveryStatus.FAILED,
                        started,
                        container.clock.now("UTC"),
                        error_type=type(error).__name__,
                        error_message=str(error),
                    ),
                )
                failures.append(label)
                logger.warning(
                    "event=history_redispatch_failed execution_id=%s channel_type=%s target=%s error_type=%s",
                    execution_id,
                    destination.channel_type,
                    destination.target,
                    type(error).__name__,
                )
        logger.info(
            "event=history_redispatch_completed execution_id=%s successful=%s failed=%s",
            execution_id,
            len(successes),
            len(failures),
        )
        return {"successful_targets": successes, "failed_targets": failures}

    @app.get("/api/logs")
    def logs(limit: int = 200) -> dict[str, object]:
        safe_limit = max(1, min(limit, 500))
        return {"lines": store.tail_log(safe_limit)}

    return app
