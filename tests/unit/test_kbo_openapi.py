from datetime import date

import httpx

from prompt_dispatcher.adapters.outbound.kbo.openapi import KboOpenApi
from prompt_dispatcher.domain.job import KboSource


def test_kbo_openapi_formats_latest_results() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/results/latest"
        assert request.url.params["team"] == "SS"
        return httpx.Response(200, json={"games": [{"id": 1, "status": "completed"}]})

    api = KboOpenApi("http://kbo.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = api.fetch(KboSource("samsung", "삼성 최근 결과", team="SS"), date(2026, 8, 5))

    assert "삼성 최근 결과" in result
    assert '"completed"' in result


def test_kbo_openapi_collects_before_games_query() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/internal/v1/collections":
            assert request.headers["authorization"] == "Bearer admin-key"
            return httpx.Response(200, json={"insertedCount": 1})
        assert request.url.path == "/api/v1/games"
        assert request.url.params["date"] == "2026-08-05"
        return httpx.Response(200, json={"games": []})

    api = KboOpenApi(
        "http://kbo.test", "admin-key", httpx.Client(transport=httpx.MockTransport(handler))
    )
    api.fetch(KboSource("today", "오늘 경기", "games", collect_before_fetch=True), date(2026, 8, 5))

    assert calls == ["/internal/v1/collections", "/api/v1/games"]
