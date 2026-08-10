import httpx
import pytest

from prompt_dispatcher.adapters.outbound.openwebui.http_adapter import HttpOpenWebUiAdapter
from prompt_dispatcher.domain.errors import OpenWebUiError
from prompt_dispatcher.domain.job import OpenWebUiRequest, OpenWebUiResponse


def test_chat_backed_streaming_error_includes_response_detail() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/chats/new":
            return httpx.Response(200, json={"id": "chat-id"})
        assert request.url.path == "/api/chat/completions"
        return httpx.Response(400, json={"detail": "invalid model input"})

    adapter = HttpOpenWebUiAdapter(
        "https://openwebui.example.com",
        "test-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(OpenWebUiError, match="HTTP 400.*invalid model input"):
        adapter.generate(OpenWebUiRequest("test-model", "prompt"))


def test_chat_generation_leaves_retries_to_configured_use_case(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = HttpOpenWebUiAdapter("https://openwebui.example.com", "test-key")
    def generate_once(_: OpenWebUiRequest) -> OpenWebUiResponse:
        raise OpenWebUiError("Open WebUI chat-backed generation failed (HTTP 400): Model not found")

    monkeypatch.setattr(adapter, "_generate_in_chat", generate_once)

    with pytest.raises(OpenWebUiError, match="Model not found"):
        adapter.generate(OpenWebUiRequest("test-model", "prompt"))
