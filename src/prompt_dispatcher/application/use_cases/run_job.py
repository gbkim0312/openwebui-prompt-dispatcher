import logging
from uuid import uuid4

from prompt_dispatcher.application.dto.commands import RunJobCommand
from prompt_dispatcher.application.dto.results import RunJobResult
from prompt_dispatcher.application.ports import (
    ClockPort,
    ExecutionRepositoryPort,
    JobRepositoryPort,
    OpenWebUiPort,
    PromptLoaderPort,
    TemplateRendererPort,
)
from prompt_dispatcher.application.ports.model_catalog import ModelCatalogPort
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.domain.delivery import DeliveryResult, OutboundMessage
from prompt_dispatcher.domain.enums import DeliveryStatus, ExecutionStatus
from prompt_dispatcher.domain.errors import JobNotFoundError
from prompt_dispatcher.domain.execution import (
    Execution,
    ExecutionResult,
    determine_execution_status,
)
from prompt_dispatcher.domain.job import OpenWebUiRequest

logger = logging.getLogger(__name__)


class RunJob:
    def __init__(
        self,
        job_repository: JobRepositoryPort,
        prompt_loader: PromptLoaderPort,
        template_renderer: TemplateRendererPort,
        openwebui: OpenWebUiPort,
        execution_repository: ExecutionRepositoryPort,
        channel_resolver: ChannelResolver,
        clock: ClockPort,
        model_catalog: ModelCatalogPort | None = None,
    ) -> None:
        self._jobs, self._prompts, self._renderer = job_repository, prompt_loader, template_renderer
        self._openwebui, self._executions, self._channels, self._clock = (
            openwebui,
            execution_repository,
            channel_resolver,
            clock,
        )
        self._model_catalog = model_catalog

    def execute(self, command: RunJobCommand) -> RunJobResult:
        if self._model_catalog is not None:
            try:
                self._model_catalog.refresh()
            except Exception:
                logger.warning("Model catalog refresh failed; using the previous cache")
        job = self._jobs.find_by_id(command.job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {command.job_id}")
        if not job.enabled:
            return RunJobResult(None, ExecutionStatus.SKIPPED, "Job is disabled")
        now = self._clock.now(job.schedule.timezone)
        scheduled = command.scheduled_time or now
        execution = Execution(str(uuid4()), job.id, scheduled, now)
        if job.execution_policy.skip_if_previous_running and self._executions.find_running(job.id):
            return RunJobResult(None, ExecutionStatus.SKIPPED, "Job already running")
        if not self._executions.try_start(execution):
            return RunJobResult(None, ExecutionStatus.SKIPPED, "Duplicate scheduled execution")
        try:
            template = self._prompts.load(job.prompt_definition)
            variables = dict(job.prompt_definition.variables) | {
                "job_id": job.id,
                "job_name": job.name,
                "scheduled_time": scheduled.isoformat(),
                "execution_time": now.isoformat(),
                "current_date": now.date().isoformat(),
                "current_datetime": now.isoformat(),
                "timezone": job.schedule.timezone,
            }
            prompt = self._renderer.render(template, variables)
            content = (
                prompt
                if command.skip_openwebui
                else self._openwebui.generate(
                    OpenWebUiRequest(
                        job.openwebui_options.model,
                        prompt,
                        job.openwebui_options.skill_ids,
                        job.openwebui_options.tool_ids,
                        job.openwebui_options.required_tool_ids,
                        job.openwebui_options.timeout_seconds,
                    )
                ).content
            )
            if not content.strip():
                raise ValueError("Open WebUI returned empty content")
        except Exception as exc:
            self._executions.complete(
                execution.id,
                ExecutionResult(
                    ExecutionStatus.FAILED,
                    self._clock.now(job.schedule.timezone),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                ),
            )
            return RunJobResult(execution.id, ExecutionStatus.FAILED, str(exc))
        if command.dry_run:
            self._executions.complete(
                execution.id,
                ExecutionResult(
                    ExecutionStatus.SUCCESS, self._clock.now(job.schedule.timezone), len(content)
                ),
            )
            return RunJobResult(execution.id, ExecutionStatus.SUCCESS, content)
        successes = failures = 0
        for destination in job.destinations:
            started = self._clock.now(job.schedule.timezone)
            try:
                channel = self._channels.resolve(
                    "fake" if command.fake_channel else destination.channel_type
                )
                receipt = channel.send(destination.target, OutboundMessage(job.name, content))
                delivery = DeliveryResult(
                    destination.channel_type,
                    destination.target,
                    DeliveryStatus.SUCCESS,
                    started,
                    self._clock.now(job.schedule.timezone),
                    receipt.external_id,
                )
                successes += 1
            except Exception as exc:
                delivery = DeliveryResult(
                    destination.channel_type,
                    destination.target,
                    DeliveryStatus.FAILED,
                    started,
                    self._clock.now(job.schedule.timezone),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
                failures += 1
            self._executions.add_delivery(execution.id, delivery)
        status = determine_execution_status(successes, failures)
        self._executions.complete(
            execution.id,
            ExecutionResult(status, self._clock.now(job.schedule.timezone), len(content)),
        )
        return RunJobResult(execution.id, status)
