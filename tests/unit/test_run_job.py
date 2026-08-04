from datetime import UTC, datetime
from typing import cast

from prompt_dispatcher.adapters.outbound.channels.fake import FakeMessageChannel
from prompt_dispatcher.adapters.outbound.openwebui.http_adapter import FakeOpenWebUiClient
from prompt_dispatcher.adapters.outbound.prompts.file_prompt_loader import FakePromptLoader
from prompt_dispatcher.adapters.outbound.repositories.in_memory import (
    InMemoryExecutionRepository,
    InMemoryJobRepository,
)
from prompt_dispatcher.adapters.outbound.search.tavily import TavilySearch
from prompt_dispatcher.adapters.outbound.system.clock import FakeClock
from prompt_dispatcher.adapters.outbound.templates.jinja_renderer import JinjaTemplateRenderer
from prompt_dispatcher.application.dto.commands import RunJobCommand
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.application.use_cases.run_job import RunJob
from prompt_dispatcher.domain.enums import ExecutionStatus
from prompt_dispatcher.domain.job import (
    ChannelDestination,
    Job,
    OpenWebUiOptions,
    OpenWebUiResponse,
    PromptDefinition,
    ResearchTask,
    Schedule,
    WeatherSource,
)


def test_run_job_delivers_and_records_success() -> None:
    job = Job(
        "news",
        "News",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model", ("skill",), ("tool",)),
        PromptDefinition(file="p.md", variables={"language": "ko"}),
        (ChannelDestination("fake", "one"),),
    )
    channel, client, repository = (
        FakeMessageChannel(),
        FakeOpenWebUiClient("answer"),
        InMemoryExecutionRepository(),
    )
    use_case = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader({"p.md": "{{ language }}"}),
        JinjaTemplateRenderer(),
        client,
        repository,
        ChannelResolver([channel]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
    )
    result = use_case.execute(RunJobCommand("news"))
    assert result.status == ExecutionStatus.SUCCESS
    assert client.requests[0].skill_ids == ()
    assert client.requests[0].tool_ids == ()
    assert channel.sent_messages[0].body == "answer"
    assert repository.result_for(result.execution_id or "").status == ExecutionStatus.SUCCESS


def test_failed_channel_does_not_stop_following_channels() -> None:
    job = Job(
        "j",
        "J",
        True,
        Schedule("0 0 * * *", "UTC"),
        OpenWebUiOptions("m"),
        PromptDefinition(text="x"),
        (ChannelDestination("fake", "bad"), ChannelDestination("fake", "good")),
    )
    channel = FakeMessageChannel({"bad"})
    repo = InMemoryExecutionRepository()
    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        FakeOpenWebUiClient(),
        repo,
        ChannelResolver([channel]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
    ).execute(RunJobCommand("j"))
    assert result.status == ExecutionStatus.PARTIAL_SUCCESS
    assert channel.sent_messages[0].target == "good"


def test_run_job_can_test_a_disabled_job() -> None:
    job = Job(
        "disabled",
        "Disabled",
        False,
        Schedule("0 0 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="hello"),
        (ChannelDestination("fake", "one"),),
    )
    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        FakeOpenWebUiClient(),
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
    ).execute(RunJobCommand("disabled", allow_disabled=True))

    assert result.status == ExecutionStatus.SUCCESS


def test_run_job_combines_research_summaries_before_single_delivery() -> None:
    class FakeTavily:
        def search(self, query: str, *_: object) -> tuple[tuple[str, str, str], ...]:
            assert query == "오늘 정치 뉴스"
            return (("정치", "https://example.com", "요약"),)

    job = Job(
        "briefing",
        "Briefing",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="최종 브리핑:\n{{ research.politics }}"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(
            ResearchTask("politics", "정치", "오늘 정치 뉴스", model="research-model"),
        ),
        research_use_parent_model=False,
    )
    channel, client = FakeMessageChannel(), FakeOpenWebUiClient("요약 결과")
    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([channel]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        tavily=cast(TavilySearch, FakeTavily()),
    ).execute(RunJobCommand("briefing"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 2
    assert client.requests[0].model == "research-model"
    assert client.requests[1].model == "model"
    assert "요약 결과" in client.requests[1].prompt
    assert channel.sent_messages[0].body == "요약 결과"


def test_failed_research_task_does_not_stop_final_briefing() -> None:
    class FakeTavily:
        def search(self, *_: object) -> tuple[tuple[str, str, str], ...]:
            return (("기사", "https://example.com", "요약"),)

    class SequencedClient:
        def __init__(self) -> None:
            self.calls = 0
            self.requests = []

        def generate(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                raise RuntimeError("first research failed")
            return OpenWebUiResponse("최종 브리핑", request.model)

    job = Job(
        "briefing",
        "Briefing",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="{{ research.bad }}\n{{ research.good }}"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(
            ResearchTask("bad", "실패 리서치", "bad", model="model"),
            ResearchTask("good", "성공 리서치", "good", model="model"),
        ),
        research_use_parent_model=False,
    )
    channel, client = FakeMessageChannel(), SequencedClient()

    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,  # type: ignore[arg-type]
        InMemoryExecutionRepository(),
        ChannelResolver([channel]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        tavily=cast(TavilySearch, FakeTavily()),
    ).execute(RunJobCommand("briefing"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 3
    assert "리서치 실패" in client.requests[-1].prompt
    assert "최종 브리핑" == channel.sent_messages[0].body


def test_run_job_skips_disabled_research_task() -> None:
    job = Job(
        "briefing",
        "Briefing",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="최종 브리핑"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(ResearchTask("economy", "경제", "오늘 경제 뉴스", enabled=False),),
    )
    client = FakeOpenWebUiClient("최종 결과")
    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
    ).execute(RunJobCommand("briefing"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 1


def test_run_job_skips_research_not_scheduled_for_today() -> None:
    job = Job(
        "briefing",
        "Briefing",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="최종 브리핑"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(
            ResearchTask("economy", "경제", "오늘 경제 뉴스", days_of_week=("fri",)),
        ),
    )
    client = FakeOpenWebUiClient("최종 결과")

    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),  # Thursday
    ).execute(RunJobCommand("briefing"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 1


def test_run_job_omits_weekday_skipped_research_from_combined_context() -> None:
    class FakeTavily:
        def search(self, *_: object) -> tuple[tuple[str, str, str], ...]:
            return (("기사", "https://example.com", "요약"),)

    job = Job(
        "briefing",
        "Briefing",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="{{ research_context }}"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(
            ResearchTask("skipped", "건너뜀", "skip", days_of_week=("fri",)),
            ResearchTask("run", "실행", "run", days_of_week=("thu",)),
        ),
    )
    client = FakeOpenWebUiClient("요약 결과")

    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),  # Thursday
        tavily=cast(TavilySearch, FakeTavily()),
    ).execute(RunJobCommand("briefing"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 2
    assert "요약 결과" in client.requests[-1].prompt


def test_run_job_injects_weather_source_into_prompt() -> None:
    class FakeWeather:
        def fetch(self, source: WeatherSource) -> str:
            assert source.id == "seoul"
            return "서울 날씨\n현재: 맑음, 25°C"

    job = Job(
        "weather",
        "Weather",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="{{ weather.seoul }}\n---\n{{ weather_context }}"),
        (ChannelDestination("fake", "one"),),
        weather_sources=(WeatherSource("seoul", "서울", 37.5665, 126.9780),),
    )
    client = FakeOpenWebUiClient("최종 결과")

    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        weather=FakeWeather(),  # type: ignore[arg-type]
    ).execute(RunJobCommand("weather"))

    assert result.status == ExecutionStatus.SUCCESS
    assert client.requests[0].prompt.count("서울 날씨") == 2


def test_weather_only_research_does_not_require_tavily() -> None:
    class FakeWeather:
        def fetch(self, _: WeatherSource) -> str:
            return "서울 날씨\n현재: 맑음"

    job = Job(
        "weather-research",
        "Weather research",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("model"),
        PromptDefinition(text="{{ research.today_weather }}"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(
            ResearchTask(
                "today_weather",
                "오늘 날씨",
                "",
                weather_sources=(WeatherSource("seoul", "서울", 37.5665, 126.9780),),
                use_web_search=False,
            ),
        ),
    )
    client = FakeOpenWebUiClient("최종 결과")

    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        weather=FakeWeather(),  # type: ignore[arg-type]
    ).execute(RunJobCommand("weather-research"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 2
    assert "구조화 날씨 데이터" in client.requests[0].prompt


def test_research_can_pass_raw_search_and_weather_data_to_final_prompt() -> None:
    class FakeWeather:
        def fetch(self, _: WeatherSource) -> str:
            return "서울 날씨\n현재: 맑음"

    class FakeTavily:
        def search(self, query: str, *_: object) -> tuple[tuple[str, str, str], ...]:
            assert query == "서울 날씨 뉴스"
            return (("날씨 뉴스", "https://example.com/weather", "맑은 날씨"),)

    job = Job(
        "raw-research",
        "Raw research",
        True,
        Schedule("0 7 * * *", "UTC"),
        OpenWebUiOptions("final-model"),
        PromptDefinition(text="최종 자료\n{{ research.weather_raw }}"),
        (ChannelDestination("fake", "one"),),
        research_tasks=(
            ResearchTask(
                "weather_raw",
                "날씨 원본",
                "서울 날씨 뉴스",
                use_prompt=False,
                weather_sources=(WeatherSource("seoul", "서울", 37.5665, 126.9780),),
            ),
        ),
    )
    client = FakeOpenWebUiClient("최종 결과")

    result = RunJob(
        InMemoryJobRepository([job]),
        FakePromptLoader(),
        JinjaTemplateRenderer(),
        client,
        InMemoryExecutionRepository(),
        ChannelResolver([FakeMessageChannel()]),
        FakeClock(datetime(2026, 1, 1, tzinfo=UTC)),
        tavily=FakeTavily(),  # type: ignore[arg-type]
        weather=FakeWeather(),  # type: ignore[arg-type]
    ).execute(RunJobCommand("raw-research"))

    assert result.status == ExecutionStatus.SUCCESS
    assert len(client.requests) == 1
    assert "--- Tavily 검색 결과 ---" in client.requests[0].prompt
    assert "--- 구조화 날씨 데이터 ---" in client.requests[0].prompt
