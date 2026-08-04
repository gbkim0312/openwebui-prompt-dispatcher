import logging
import re
import time
from datetime import datetime, timedelta
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
    WeatherPort,
)
from prompt_dispatcher.application.ports.model_catalog import ModelCatalogPort
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.application.services.markdown import normalize_markdown_ranges
from prompt_dispatcher.application.services.tavily_context import (
    enrich_with_tavily,
    format_tavily_results,
)
from prompt_dispatcher.domain.delivery import DeliveryResult, OutboundMessage
from prompt_dispatcher.domain.enums import DeliveryStatus, ExecutionStatus
from prompt_dispatcher.domain.errors import JobNotFoundError, OpenWebUiError
from prompt_dispatcher.domain.execution import (
    Execution,
    ExecutionResult,
    determine_execution_status,
)
from prompt_dispatcher.domain.job import Job, OpenWebUiRequest, OpenWebUiResponse

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
        weather: WeatherPort | None = None,
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
        self._weather = weather

    def execute(self, command: RunJobCommand) -> RunJobResult:
        available_models: set[str] | None = None
        if self._model_catalog is not None:
            try:
                self._model_catalog.refresh()
                available_models = set(self._model_catalog.list_models())
            except Exception:
                logger.warning(
                    "event=model_preflight_failed job_id=%s reason=model_catalog_unavailable",
                    command.job_id,
                )
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
            if not command.skip_openwebui:
                self._assert_models_available(job, scheduled, available_models)
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
            weather_results: dict[str, str] = {}
            for source in job.weather_sources:
                try:
                    if self._weather is None:
                        raise ValueError("Weather service is not configured")
                    logger.info(
                        "event=weather_source_started job_id=%s execution_id=%s source_id=%s",
                        job.id,
                        execution.id,
                        source.id,
                    )
                    weather_results[source.id] = self._weather.fetch(source)
                except Exception as error:
                    weather_results[source.id] = f"[날씨 정보를 가져오지 못했습니다: {source.name}]"
                    logger.warning(
                        "event=weather_source_failed job_id=%s execution_id=%s source_id=%s error_type=%s",
                        job.id,
                        execution.id,
                        source.id,
                        type(error).__name__,
                    )
            if weather_results:
                variables["weather"] = weather_results
                variables["weather_context"] = "\n\n".join(weather_results.values())
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
                    logger.info(
                        "event=research_task_started job_id=%s execution_id=%s task_id=%s use_prompt=%s",
                        job.id,
                        execution.id,
                        task.id,
                        task.use_prompt,
                    )
                    weather_context: list[str] = []
                    for source in task.weather_sources:
                        if self._weather is None:
                            raise ValueError("Weather service is not configured")
                        weather_context.append(self._weather.fetch(source))
                    source_context: list[str] = []
                    if weather_context:
                        source_context.append(
                            "--- 구조화 날씨 데이터 ---\n" + "\n\n".join(weather_context)
                        )
                    if task.use_web_search:
                        search_query = self._renderer.render(task.query, variables)
                        if self._tavily is None:
                            raise ValueError("TAVILY_API_KEY is required for Web Search with Tavily")
                        results = self._tavily.search(
                            search_query,
                            task.time_range,
                            task.topic,
                            task.search_depth,
                            task.max_results,
                            task.include_domains,
                            task.exclude_domains,
                            task.include_raw_content,
                        )
                        source_context.append("--- Tavily 검색 결과 ---\n" + format_tavily_results(results))
                    if task.use_prompt:
                        task_model = (
                            job.openwebui_options.model
                            if job.research_use_parent_model
                            else task.model
                        )
                        if not task_model:
                            raise ValueError(f"Research task model is required: {task.id}")
                        summary_instruction = self._renderer.render(
                            task.summary_prompt
                            or f"{task.name} 관련 검색 결과를 한국어로 핵심 사실과 출처 중심으로 요약하세요.",
                            variables,
                        )
                        research_prompt = summary_instruction + "\n\n" + "\n\n".join(source_context)
                        response = self._generate_with_retry(
                            OpenWebUiRequest(task_model, research_prompt), job
                        )
                        if not response.content.strip():
                            raise ValueError(f"Research task returned empty content: {task.id}")
                        research_results[task.id] = response.content
                    else:
                        research_results[task.id] = "\n\n".join(source_context)
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
                content = self._generate_with_retry(
                    OpenWebUiRequest(
                        job.openwebui_options.model,
                        prompt,
                        (),
                        tool_ids,
                        job.openwebui_options.required_tool_ids,
                        job.openwebui_options.timeout_seconds,
                    ),
                    job,
                ).content
            if not content.strip():
                raise ValueError("Open WebUI returned empty content")
            content = normalize_markdown_ranges(content)
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

    def _assert_models_available(
        self, job: Job, scheduled_time: datetime, available_models: set[str] | None
    ) -> None:
        """Fail before paid external research when the selected Open WebUI model is unavailable."""
        if self._model_catalog is None:
            return
        if available_models is None:
            raise OpenWebUiError(
                "Open WebUI model availability could not be verified; Tavily search was not started"
            )

        current_day = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")[
            scheduled_time.weekday()
        ]
        required: list[tuple[str, str]] = [("최종 작업", job.openwebui_options.model)]
        for task in job.research_tasks:
            if not task.enabled or not task.use_prompt:
                continue
            if task.days_of_week and current_day not in task.days_of_week:
                continue
            model = job.openwebui_options.model if job.research_use_parent_model else task.model
            if not model:
                raise ValueError(f"Research task model is required: {task.id}")
            required.append((f"리서치 {task.name}", model))

        unavailable = [f"{label} ({model})" for label, model in required if model not in available_models]
        if unavailable:
            raise OpenWebUiError(
                "Open WebUI model not available; Tavily search was not started: "
                + ", ".join(unavailable)
            )
        logger.info(
            "event=model_preflight_succeeded job_id=%s model_count=%s",
            job.id,
            len(required),
        )

    def _generate_with_retry(self, request: OpenWebUiRequest, job: Job) -> OpenWebUiResponse:
        policy = job.execution_policy
        for attempt in range(policy.retry_count + 1):
            try:
                return self._openwebui.generate(request)
            except OpenWebUiError as error:
                if attempt >= policy.retry_count or not self._is_retryable_openwebui_error(error):
                    raise
                delay = max(1, policy.retry_delay_seconds)
                logger.warning(
                    "event=openwebui_generation_retry job_id=%s model=%s attempt=%s delay_seconds=%s error=%s",
                    job.id,
                    request.model,
                    attempt + 1,
                    delay,
                    str(error).replace("\n", " "),
                )
                time.sleep(delay)
        raise AssertionError("unreachable")

    @staticmethod
    def _is_retryable_openwebui_error(error: OpenWebUiError) -> bool:
        message = str(error).lower()
        return (
            "model not found" in message
            or "timed out" in message
            or "connection" in message
            or re.search(r"http (408|409|425|429|5\d\d)", message) is not None
        )
