from prompt_dispatcher.adapters.outbound.openwebui.http_adapter import FakeOpenWebUiClient
from prompt_dispatcher.adapters.outbound.system.clock import SystemClock
from prompt_dispatcher.application.services.channel_resolver import ChannelResolver
from prompt_dispatcher.application.use_cases.send_prompt import SendPrompt, SendPromptCommand


def test_send_prompt_passes_selected_skills_and_tools() -> None:
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
    assert client.requests[0].skill_ids == ("skill-1",)
    assert client.requests[0].tool_ids == ("tool-1",)
    assert client.requests[0].timeout_seconds == 123
