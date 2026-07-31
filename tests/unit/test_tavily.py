import json
from typing import cast

import httpx
import pytest

from prompt_dispatcher.adapters.outbound.search.tavily import TavilySearch
from prompt_dispatcher.application.services.tavily_context import (
    TAVILY_TOOL_ID,
    enrich_with_tavily,
)


def test_tavily_search_uses_expected_api_request() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "results": [
                    {"title": "News", "url": "https://example.com/news", "content": "Summary"}
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    search = TavilySearch("tvly-test", client)

    assert search.search("latest AI news") == (("News", "https://example.com/news", "Summary"),)
    assert captured == {
        "authorization": "Bearer tvly-test",
        "payload": {
            "query": "latest AI news",
            "topic": "news",
            "time_range": "week",
            "search_depth": "basic",
            "max_results": 8,
        },
    }


def test_tavily_tool_is_replaced_with_search_context() -> None:
    class FakeTavily:
        def search(self, query: str, time_range: str = "week") -> tuple[tuple[str, str, str], ...]:
            assert query == "AI 뉴스 5개"
            assert time_range == "week"
            return (("첫 뉴스", "https://example.com/one", "첫 번째 요약"),)

    prompt, tool_ids = enrich_with_tavily(
        "AI 뉴스 5개",
        (TAVILY_TOOL_ID, "other-tool"),
        cast(TavilySearch, FakeTavily()),
    )

    assert tool_ids == ("other-tool",)
    assert "https://example.com/one" in prompt
    assert "최근 7일" in prompt


def test_tavily_requires_api_key() -> None:
    with pytest.raises(ValueError, match="TAVILY_API_KEY"):
        TavilySearch("").search("latest news")


def test_tavily_search_passes_selected_time_range() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["time_range"] == "month"
        return httpx.Response(200, json={"results": []})

    client = httpx.Client(transport=httpx.MockTransport(handler))

    assert TavilySearch("tvly-test", client).search("AI 뉴스", "month") == ()
