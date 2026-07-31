import os
from dataclasses import dataclass
from typing import cast

from prompt_dispatcher.adapters.inbound.scheduler.apscheduler_adapter import ApschedulerAdapter
from prompt_dispatcher.adapters.outbound.channels.fake import FakeMessageChannel
from prompt_dispatcher.adapters.outbound.channels.nextcloud_talk import NextcloudTalkChannel
from prompt_dispatcher.adapters.outbound.channels.telegram import TelegramChannel
from prompt_dispatcher.adapters.outbound.openwebui.cached_model_catalog import CachedModelCatalog
from prompt_dispatcher.adapters.outbound.openwebui.http_adapter import HttpOpenWebUiAdapter
from prompt_dispatcher.adapters.outbound.prompts.file_prompt_loader import FilePromptLoader
from prompt_dispatcher.adapters.outbound.repositories.sqlite_execution import (
    SqliteExecutionRepository,
)
from prompt_dispatcher.adapters.outbound.repositories.yaml_job import YamlJobRepository
from prompt_dispatcher.adapters.outbound.system.clock import SystemClock
from prompt_dispatcher.adapters.outbound.templates.jinja_renderer import JinjaTemplateRenderer
from prompt_dispatcher.application.ports.message_channel import MessageChannelPort
from prompt_dispatcher.application.ports.model_catalog import ModelCatalogPort
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.application.use_cases.jobs import ListJobs
from prompt_dispatcher.application.use_cases.register_schedules import RegisterSchedules
from prompt_dispatcher.application.use_cases.run_job import RunJob
from prompt_dispatcher.application.use_cases.send_prompt import SendPrompt

from .settings import Settings, _managed_values


def _target(
    prefix: str, target: str, suffixes: tuple[str, ...], managed: dict[str, str]
) -> tuple[str, ...] | None:
    values = tuple(
        os.getenv(f"{prefix}_{target.upper().replace('-', '_')}_{suffix}")
        or managed.get(f"{prefix}_{target.upper().replace('-', '_')}_{suffix}", "")
        for suffix in suffixes
    )
    return values if all(values) else None


@dataclass
class ApplicationContainer:
    settings: Settings
    jobs: YamlJobRepository
    run_job: RunJob
    list_jobs: ListJobs
    scheduler: ApschedulerAdapter
    register_schedules: RegisterSchedules
    model_catalog: ModelCatalogPort
    send_prompt: SendPrompt


def build_container(settings: Settings | None = None) -> ApplicationContainer:
    settings = settings or Settings.from_environment()
    jobs = YamlJobRepository(settings.jobs_directory)
    managed = _managed_values(settings.database_path.parent / "management.env")
    telegram_targets = {
        d.target: value
        for j in jobs.find_all()
        for d in j.destinations
        if d.channel_type == "telegram"
        if (value := _target("TELEGRAM", d.target, ("BOT_TOKEN", "CHAT_ID"), managed))
    }
    talk_targets = {
        d.target: value
        for j in jobs.find_all()
        for d in j.destinations
        if d.channel_type == "nextcloud_talk"
        if (
            value := _target(
                "NEXTCLOUD_TALK", d.target, ("USERNAME", "APP_PASSWORD", "ROOM_TOKEN"), managed
            )
        )
    }
    channels: list[MessageChannelPort] = [
        TelegramChannel(cast(dict[str, tuple[str, str]], telegram_targets)),
        NextcloudTalkChannel(
            settings.nextcloud_url,
            cast(dict[str, tuple[str, str, str]], talk_targets),
            settings.nextcloud_verify_tls,
        ),
    ]
    if settings.enable_fake_channel:
        channels.append(FakeMessageChannel())
    scheduler, clock = ApschedulerAdapter(), SystemClock()
    openwebui = HttpOpenWebUiAdapter(
        settings.openwebui_base_url, settings.openwebui_api_key, settings.openwebui_verify_tls
    )
    model_catalog = CachedModelCatalog(openwebui, settings.database_path.parent / "models.json")
    run = RunJob(
        jobs,
        FilePromptLoader(settings.prompts_directory),
        JinjaTemplateRenderer(),
        openwebui,
        SqliteExecutionRepository(settings.database_path),
        ChannelResolver(channels),
        clock,
        model_catalog,
    )
    send_prompt = SendPrompt(openwebui, ChannelResolver(channels), clock)
    return ApplicationContainer(
        settings,
        jobs,
        run,
        ListJobs(jobs),
        scheduler,
        RegisterSchedules(jobs, scheduler, run),
        model_catalog,
        send_prompt,
    )
