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
        if request.url.path == "/internal/v1/collections/all":
            assert request.headers["authorization"] == "Bearer admin-key"
            return httpx.Response(200, json={"insertedCount": 1})
        assert request.url.path == "/api/v1/games"
        assert request.url.params["date"] == "2026-08-05"
        return httpx.Response(200, json={"games": []})

    api = KboOpenApi(
        "http://kbo.test", "admin-key", httpx.Client(transport=httpx.MockTransport(handler))
    )
    api.fetch(KboSource("today", "오늘 경기", "games", collect_before_fetch=True), date(2026, 8, 5))

    assert calls == ["/internal/v1/collections/all", "/api/v1/games"]


def test_kbo_openapi_supports_game_analysis_and_record_collection() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/internal/v1/games/42/preview/collect":
            return httpx.Response(200, json={"updated": True})
        assert request.url.path == "/api/v1/games/42/analysis"
        return httpx.Response(200, json={"officialAnalysis": {"summary": "preview"}})

    api = KboOpenApi(
        "http://kbo.test", "admin-key", httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = api.fetch(
        KboSource("analysis", "경기 공식 분석", "analysis", game_id=42, collect_before_fetch=True),
        date(2026, 8, 5),
    )

    assert calls == ["/internal/v1/games/42/preview/collect", "/api/v1/games/42/analysis"]
    assert "officialAnalysis" in result


def test_kbo_openapi_resolves_game_id_from_team() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/results/latest":
            assert request.url.params["team"] == "SS"
            return httpx.Response(200, json={"games": [{"id": 73}]})
        assert request.url.path == "/api/v1/games/73/details"
        return httpx.Response(200, json={"winningHit": "single"})

    api = KboOpenApi("http://kbo.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = api.fetch(KboSource("detail", "삼성 최근 경기", "game_details", team="SS"), date(2026, 8, 5))

    assert calls == ["/api/v1/results/latest", "/api/v1/games/73/details"]
    assert "선택 경기 ID: 73" in result


def test_kbo_rankings_omits_date_when_not_selected() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/rankings"
        assert "date" not in request.url.params
        return httpx.Response(200, json={"rankings": []})

    api = KboOpenApi("http://kbo.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    api.fetch(KboSource("ranking", "최신 순위", "rankings"), date(2026, 8, 5))


def test_kbo_latest_results_uses_execution_date_only_when_enabled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/results/latest"
        assert request.url.params["date"] == "2026-08-05"
        return httpx.Response(200, json={"games": []})

    api = KboOpenApi("http://kbo.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    api.fetch(KboSource("today", "오늘 종료 경기", use_today=True), date(2026, 8, 5))


def test_kbo_game_detail_resolves_completed_game_on_execution_date() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/games":
            assert request.url.params["date"] == "2026-08-05"
            assert request.url.params["team"] == "SS"
            assert request.url.params["status"] == "completed"
            return httpx.Response(200, json={"games": [{"id": 88}]})
        assert request.url.path == "/api/v1/games/88/details"
        return httpx.Response(200, json={"winningHit": "double"})

    api = KboOpenApi("http://kbo.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = api.fetch(
        KboSource("detail", "오늘 삼성 경기 상세", "game_details", team="SS", use_today=True),
        date(2026, 8, 5),
    )

    assert calls == ["/api/v1/games", "/api/v1/games/88/details"]
    assert "선택 경기 ID: 88" in result


def test_kbo_lineup_resolves_game_on_specified_date() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/games":
            assert request.url.params["date"] == "2026-08-03"
            assert request.url.params["team"] == "SS"
            return httpx.Response(200, json={"games": [{"id": 91}]})
        assert request.url.path == "/api/v1/games/91/lineups"
        return httpx.Response(200, json={"confirmed": True, "lineup": []})

    api = KboOpenApi("http://kbo.test", client=httpx.Client(transport=httpx.MockTransport(handler)))
    result = api.fetch(
        KboSource(
            "lineup",
            "특정일 삼성 라인업",
            "lineups",
            team="SS",
            reference_date="2026-08-03",
        ),
        date(2026, 8, 5),
    )

    assert "선택 경기 ID: 91" in result
