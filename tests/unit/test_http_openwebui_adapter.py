import httpx
import pytest

from prompt_dispatcher.adapters.outbound.openwebui.http_adapter import HttpOpenWebUiAdapter
from prompt_dispatcher.domain.errors import OpenWebUiError
from prompt_dispatcher.domain.job import OpenWebUiRequest


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
