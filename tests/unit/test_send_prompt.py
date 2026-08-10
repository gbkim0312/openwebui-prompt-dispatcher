from prompt_dispatcher.adapters.outbound.openwebui.http_adapter import FakeOpenWebUiClient
from prompt_dispatcher.adapters.outbound.system.clock import SystemClock
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.application.use_cases.send_prompt import SendPrompt, SendPromptCommand
from prompt_dispatcher.domain.errors import OpenWebUiError


def test_send_prompt_uses_no_skills_or_tools_without_web_search() -> None:
    client = FakeOpenWebUiClient("answer")
    use_case = SendPrompt(client, ChannelResolver([]), SystemClock())

    result = use_case.execute(
        SendPromptCommand(
            prompt="hello",
            model="test-model",
            destinations=(),
            skill_ids=("skill-1",),
            tool_ids=("tool-1",),
            timeout_seconds=123,
            dry_run=True,
        )
    )

    assert result.content == "answer"
    assert client.requests[0].skill_ids == ()
    assert client.requests[0].tool_ids == ()
    assert client.requests[0].timeout_seconds == 123


def test_send_prompt_reloads_model_catalog_before_retry(monkeypatch) -> None:
    class FlakyClient:
        def __init__(self) -> None:
            self.calls = 0
        def generate(self, request):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                raise OpenWebUiError("Model not found")
            return type("Response", (), {"content": "answer"})()

    class Catalog:
        revision = "test"
        def __init__(self) -> None:
            self.refresh_calls = 0
        def refresh(self) -> bool:
            self.refresh_calls += 1
            return False
        def list_models(self) -> tuple[str, ...]:
            return ("test-model",)

    catalog, client = Catalog(), FlakyClient()
    monkeypatch.setattr("prompt_dispatcher.application.use_cases.send_prompt.time.sleep", lambda _: None)
    result = SendPrompt(
        client,  # type: ignore[arg-type]
        ChannelResolver([]),
        SystemClock(),
        model_catalog=catalog,
        openwebui_retry_count=1,
        openwebui_retry_delay_seconds=1,
    ).execute(SendPromptCommand(prompt="hello", model="test-model", destinations=(), dry_run=True))

    assert result.content == "answer"
    assert catalog.refresh_calls == 2
