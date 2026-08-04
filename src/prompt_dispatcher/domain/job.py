from collections.abc import Mapping
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Schedule:
    cron: str
    timezone: str


@dataclass(frozen=True)
class OpenWebUiOptions:
    model: str
    skill_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    required_tool_ids: tuple[str, ...] = ()
    timeout_seconds: int = 600
    web_search_time_range: str | None = None
    web_search_query: str | None = None
    web_search_topic: str = "news"
    web_search_depth: str = "basic"
    web_search_max_results: int = 8
    web_search_include_domains: tuple[str, ...] = ()
    web_search_exclude_domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class PromptDefinition:
    file: str | None = None
    text: str | None = None
    variables: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelDestination:
    channel_type: str
    target: str
    options: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionPolicy:
    max_instances: int = 1
    skip_if_previous_running: bool = True
    misfire_grace_seconds: int = 300
    retry_count: int = 0
    retry_delay_seconds: int = 1


@dataclass(frozen=True)
class ResearchTask:
    id: str
    name: str
    query: str
    summary_prompt: str = ""
    time_range: str = "day"
    topic: str = "news"
    search_depth: str = "basic"
    max_results: int = 5
    include_domains: tuple[str, ...] = ()
    exclude_domains: tuple[str, ...] = ()
    model: str | None = None
    enabled: bool = True
    # Empty means every day on which the parent job runs. Values are cron
    # weekday names: mon through sun.
    days_of_week: tuple[str, ...] = ()
    include_raw_content: bool = False
    use_web_search: bool = True
    weather_sources: "tuple[WeatherSource, ...]" = ()


@dataclass(frozen=True)
class WeatherSource:
    id: str
    name: str
    latitude: float
    longitude: float
    timezone: str = "Asia/Seoul"
    include_current: bool = True
    include_daily: bool = True
    forecast_days: int = 2


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    enabled: bool
    schedule: Schedule
    openwebui_options: OpenWebUiOptions
    prompt_definition: PromptDefinition
    destinations: tuple[ChannelDestination, ...]
    execution_policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    research_tasks: tuple[ResearchTask, ...] = ()
    research_use_parent_model: bool = True
    weather_sources: tuple[WeatherSource, ...] = ()


@dataclass(frozen=True)
class OpenWebUiRequest:
    model: str
    prompt: str
    skill_ids: tuple[str, ...] = ()
    tool_ids: tuple[str, ...] = ()
    required_tool_ids: tuple[str, ...] = ()
    timeout_seconds: int = 600


@dataclass(frozen=True)
class OpenWebUiResponse:
    content: str
    model: str | None = None
    tool_calls: tuple[str, ...] = ()
