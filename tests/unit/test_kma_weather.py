from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

from prompt_dispatcher.adapters.outbound.weather.kma import KmaWeather
from prompt_dispatcher.domain.job import WeatherSource


def test_kma_weather_formats_current_and_daily_forecast() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("getUltraSrtNcst"):
            items = [
                {"category": "PTY", "obsrValue": "0"},
                {"category": "T1H", "obsrValue": "29.7"},
                {"category": "REH", "obsrValue": "70"},
                {"category": "RN1", "obsrValue": "강수없음"},
                {"category": "WSD", "obsrValue": "1.2"},
            ]
        elif request.url.path.endswith("getUltraSrtFcst"):
            items = [
                {"fcstDate": "20260804", "fcstTime": "0800", "category": "SKY", "fcstValue": "1"},
                {"fcstDate": "20260804", "fcstTime": "0800", "category": "PTY", "fcstValue": "0"},
                {"fcstDate": "20260804", "fcstTime": "0800", "category": "T1H", "fcstValue": "30"},
                {"fcstDate": "20260804", "fcstTime": "0800", "category": "POP", "fcstValue": "10"},
                {"fcstDate": "20260804", "fcstTime": "0800", "category": "REH", "fcstValue": "65"},
                {"fcstDate": "20260804", "fcstTime": "0800", "category": "WSD", "fcstValue": "1.5"},
            ]
        else:
            items = [
                {"fcstDate": "20260804", "fcstTime": "1200", "category": "SKY", "fcstValue": "1"},
                {"fcstDate": "20260804", "fcstTime": "1200", "category": "PTY", "fcstValue": "0"},
                {"fcstDate": "20260804", "fcstTime": "0600", "category": "TMN", "fcstValue": "24"},
                {"fcstDate": "20260804", "fcstTime": "1500", "category": "TMX", "fcstValue": "35"},
                {"fcstDate": "20260804", "fcstTime": "0900", "category": "POP", "fcstValue": "10"},
                {"fcstDate": "20260805", "fcstTime": "1200", "category": "SKY", "fcstValue": "4"},
                {"fcstDate": "20260805", "fcstTime": "1200", "category": "PTY", "fcstValue": "1"},
                {"fcstDate": "20260805", "fcstTime": "0600", "category": "TMN", "fcstValue": "25"},
                {"fcstDate": "20260805", "fcstTime": "1500", "category": "TMX", "fcstValue": "33"},
                {"fcstDate": "20260805", "fcstTime": "0900", "category": "POP", "fcstValue": "60"},
            ]
        return httpx.Response(200, json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}})

    weather = KmaWeather(
        "service-key",
        httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 8, 4, 7, 30, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    report = weather.fetch(WeatherSource("seoul", "서울", 37.5665, 126.9780))

    assert len(requests) == 6
    assert requests[0].url.params["nx"] == "60"
    assert requests[0].url.params["ny"] == "127"
    assert requests[0].url.params["base_time"] == "0600"
    assert requests[1].url.params["base_time"] == "0630"
    assert requests[2].url.params["base_time"] == "0500"
    assert "현재 실황 (2026-08-04 06:00 발표): 강수 없음; 기온 29.7°C" in report
    assert "일일 예보 (2026-08-04): 날씨 상태 맑음; 최저 24°C, 최고 35°C; 일 최대 강수확률 10%" in report
    assert "일일 예보 (2026-08-05): 날씨 상태 비;" in report
    assert "시간대별 초단기 예보 (2026-08-04 06:30 발표):" in report
    assert "2026-08-04 08:00: 맑음; 기온 30°C, 강수확률 10%" in report


def test_kma_weather_can_include_alerts_and_weekly_forecast() -> None:
    def response(items: list[dict[str, object]]) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}},
        )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getWthrWrnList"):
            return response([{"title": "서울특별시 호우주의보", "tmFc": "202608040700"}])
        if request.url.path.endswith("getMidLandFcst"):
            return response([{"wf3Am": "맑음", "rnSt3Am": 10}])
        if request.url.path.endswith("getMidTa"):
            return response([{"taMin3": 24, "taMax3": 33}])
        return response([])

    weather = KmaWeather(
        "service-key",
        httpx.Client(transport=httpx.MockTransport(handler)),
        now=lambda: datetime(2026, 8, 4, 7, 30, tzinfo=ZoneInfo("Asia/Seoul")),
    )

    report = weather.fetch(
        WeatherSource(
            "seoul",
            "서울",
            37.5665,
            126.9780,
            include_current=False,
            include_daily=False,
            include_alerts=True,
            include_weekly=True,
        )
    )

    assert "기상특보 (서울 관할): 서울특별시 호우주의보 (202608040700)" in report
    assert "주간 예보 (서울, 202608040600 발표):" in report
    assert "3일 후: 오전 맑음, 강수확률 10%, 최저 24°C, 최고 33°C" in report
