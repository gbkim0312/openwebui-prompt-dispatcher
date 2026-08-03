import logging
from datetime import timedelta
from uuid import uuid4

from prompt_dispatcher.adapters.outbound.search.tavily import TavilySearch
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
from prompt_dispatcher.application.services.tavily_context import enrich_with_tavily
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
        tavily: TavilySearch | None = None,
        retention_days: int = 30,
    ) -> None:
        self._jobs, self._prompts, self._renderer = job_repository, prompt_loader, template_renderer
        self._openwebui, self._executions, self._channels, self._clock = (
            openwebui,
            execution_repository,
            channel_resolver,
            clock,
        )
        self._model_catalog = model_catalog
        self._tavily = tavily
        self._retention_days = retention_days

    def execute(self, command: RunJobCommand) -> RunJobResult:
        if self._model_catalog is not None:
            try:
                self._model_catalog.refresh()
            except Exception:
                logger.warning("Model catalog refresh failed; using the previous cache")
        job = self._jobs.find_by_id(command.job_id)
        if job is None:
            raise JobNotFoundError(f"Job not found: {command.job_id}")
        if not job.enabled and not command.allow_disabled:
            logger.info("event=job_skipped job_id=%s reason=disabled", job.id)
            return RunJobResult(None, ExecutionStatus.SKIPPED, "Job is disabled")
        now = self._clock.now(job.schedule.timezone)
        self._executions.purge_before(now - timedelta(days=self._retention_days))
        scheduled = command.scheduled_time or now
        execution = Execution(str(uuid4()), job.id, scheduled, now)
        logger.info("event=job_started job_id=%s execution_id=%s", job.id, execution.id)
        if job.execution_policy.skip_if_previous_running and self._executions.find_running(job.id):
            logger.info("event=job_skipped job_id=%s reason=already_running", job.id)
            return RunJobResult(None, ExecutionStatus.SKIPPED, "Job already running")
        if not self._executions.try_start(execution):
            logger.info("event=job_skipped job_id=%s reason=duplicate_schedule", job.id)
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
            research_results: dict[str, str] = {}
            research_failures: dict[str, str] = {}
            for task in job.research_tasks:
                if not task.enabled:
                    logger.info("event=research_task_skipped job_id=%s task_id=%s", job.id, task.id)
                    continue
                current_day = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[
                    scheduled.weekday()
                ]
                if task.days_of_week and current_day not in task.days_of_week:
                    logger.info(
                        "event=research_task_skipped job_id=%s task_id=%s reason=weekday day=%s",
                        job.id,
                        task.id,
                        current_day,
                    )
                    continue
                try:
                    task_model = (
                        job.openwebui_options.model if job.research_use_parent_model else task.model
                    )
                    if not task_model:
                        raise ValueError(f"Research task model is required: {task.id}")
                    logger.info(
                        "event=research_task_started job_id=%s execution_id=%s task_id=%s model=%s",
                        job.id,
                        execution.id,
                        task.id,
                        task_model,
                    )
                    search_query = self._renderer.render(task.query, variables)
                    summary_instruction = self._renderer.render(
                        task.summary_prompt
                        or f"{task.name} 관련 검색 결과를 한국어로 핵심 사실과 출처 중심으로 요약하세요.",
                        variables,
                    )
                    research_prompt, _ = enrich_with_tavily(
                        summary_instruction,
                        ("web_search_with_tavily",),
                        self._tavily,
                        task.time_range,
                        search_query,
                        task.topic,
                        task.search_depth,
                        task.max_results,
                        task.include_domains,
                        task.exclude_domains,
                    )
                    response = self._openwebui.generate(OpenWebUiRequest(task_model, research_prompt))
                    if not response.content.strip():
                        raise ValueError(f"Research task returned empty content: {task.id}")
                    research_results[task.id] = response.content
                except Exception as error:
                    research_failures[task.id] = type(error).__name__
                    research_results[task.id] = (
                        f"[리서치 실패: {task.name} 결과를 가져오지 못했습니다. "
                        "이 항목은 최종 브리핑에서 제외하세요.]"
                    )
                    logger.warning(
                        "event=research_task_failed job_id=%s execution_id=%s task_id=%s error_type=%s",
                        job.id,
                        execution.id,
                        task.id,
                        type(error).__name__,
                    )
            if research_results:
                variables["research"] = research_results
                variables["research_failures"] = research_failures
                variables["research_context"] = "\n\n".join(
                    f"## {task.name}\n{research_results[task.id]}"
                    for task in job.research_tasks
                    if task.enabled and task.id in research_results
                )
            prompt = self._renderer.render(template, variables)
            if command.skip_openwebui:
                content = prompt
            else:
                tool_ids: tuple[str, ...] = ()
                if job.openwebui_options.web_search_time_range:
                    tool_ids = ("web_search_with_tavily",)
                final_search_query: str | None = (
                    self._renderer.render(job.openwebui_options.web_search_query, variables)
                    if job.openwebui_options.web_search_query
                    else None
                )
                prompt, tool_ids = enrich_with_tavily(
                    prompt,
                    tool_ids,
                    self._tavily,
                    job.openwebui_options.web_search_time_range or "week",
                    final_search_query,
                    job.openwebui_options.web_search_topic,
                    job.openwebui_options.web_search_depth,
                    job.openwebui_options.web_search_max_results,
                    job.openwebui_options.web_search_include_domains,
                    job.openwebui_options.web_search_exclude_domains,
                )
                content = self._openwebui.generate(
                    OpenWebUiRequest(
                        job.openwebui_options.model,
                        prompt,
                        (),
                        tool_ids,
                        job.openwebui_options.required_tool_ids,
                        job.openwebui_options.timeout_seconds,
                    )
                ).content
            if not content.strip():
                raise ValueError("Open WebUI returned empty content")
            logger.info(
                "event=openwebui_response job_id=%s execution_id=%s response_length=%s",
                job.id,
                execution.id,
                len(content),
            )
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
            logger.error(
                "event=job_failed job_id=%s execution_id=%s error_type=%s error_message=%s",
                job.id,
                execution.id,
                type(exc).__name__,
                str(exc).replace("\n", " "),
            )
            return RunJobResult(execution.id, ExecutionStatus.FAILED, str(exc))
        if command.dry_run:
            self._executions.complete(
                execution.id,
                ExecutionResult(
                    ExecutionStatus.SUCCESS,
                    self._clock.now(job.schedule.timezone),
                    len(content),
                    response_content=content,
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
                logger.info(
                    "event=delivery_success job_id=%s execution_id=%s channel_type=%s target=%s",
                    job.id,
                    execution.id,
                    destination.channel_type,
                    destination.target,
                )
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
                logger.warning(
                    "event=delivery_failed job_id=%s execution_id=%s channel_type=%s target=%s error_type=%s error_message=%s",
                    job.id,
                    execution.id,
                    destination.channel_type,
                    destination.target,
                    type(exc).__name__,
                    str(exc).replace("\n", " "),
                )
            self._executions.add_delivery(execution.id, delivery)
        status = determine_execution_status(successes, failures)
        self._executions.complete(
            execution.id,
            ExecutionResult(
                status,
                self._clock.now(job.schedule.timezone),
                len(content),
                response_content=content,
            ),
        )
        logger.info(
            "event=job_completed job_id=%s execution_id=%s status=%s", job.id, execution.id, status
        )
        return RunJobResult(execution.id, status)
