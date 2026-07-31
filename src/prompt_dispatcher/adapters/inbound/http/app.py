from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from prompt_dispatcher.adapters.outbound.repositories.web_management import WebManagementStore
from prompt_dispatcher.application.dto.commands import RunJobCommand
from prompt_dispatcher.bootstrap.container import ApplicationContainer


class JobPayload(BaseModel):
    document: dict[str, Any]
    prompt: str = ""


class SecretPayload(BaseModel):
    values: dict[str, str] = Field(default_factory=dict)


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
            },
            "prompt": store.read_prompt(job_id),
        }

    @app.put("/api/jobs/{job_id}")
    def save_job(job_id: str, payload: JobPayload) -> dict[str, str]:
        try:
            store.save_job(job_id, payload.document, payload.prompt)
            container.jobs.reload()
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
        job_id: str, dry_run: bool = False, skip_openwebui: bool = False
    ) -> dict[str, str | None]:
        result = container.run_job.execute(
            RunJobCommand(job_id, dry_run=dry_run, skip_openwebui=skip_openwebui)
        )
        return {
            "status": result.status,
            "execution_id": result.execution_id,
            "message": result.message,
        }

    @app.get("/api/settings")
    def settings() -> dict[str, object]:
        return {"configured": sorted(store.configured_keys()), "restart_required": True}

    @app.put("/api/settings")
    def save_settings(payload: SecretPayload) -> dict[str, str]:
        store.save_secrets(payload.values)
        return {"status": "saved", "message": "Restart the service to apply connection settings."}

    return app
