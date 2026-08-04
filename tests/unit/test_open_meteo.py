import httpx

from prompt_dispatcher.adapters.outbound.weather.open_meteo import OpenMeteoWeather
from prompt_dispatcher.domain.job import WeatherSource


def test_open_meteo_formats_current_and_daily_weather() -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(dict(request.url.params))
        return httpx.Response(
            200,
            json={
                "current": {
                    "time": "2026-08-04T07:00",
                    "temperature_2m": 25.2,
                    "apparent_temperature": 26.1,
                    "relative_humidity_2m": 72,
                    "weather_code": 0,
                    "precipitation": 0,
                    "wind_speed_10m": 10,
                },
                "daily": {
                    "time": ["2026-08-04", "2026-08-05"],
                    "weather_code": [0, 61],
                    "temperature_2m_min": [20, 21],
                    "temperature_2m_max": [30, 31],
                    "precipitation_probability_max": [0, 60],
                    "precipitation_sum": [0, 3.2],
                },
            },
        )

    weather = OpenMeteoWeather(httpx.Client(transport=httpx.MockTransport(handler)))
    report = weather.fetch(WeatherSource("seoul", "서울", 37.5665, 126.9780))

    assert captured["timezone"] == "Asia/Seoul"
    assert captured["temperature_unit"] == "celsius"
    assert "현재 (2026-08-04T07:00): 맑음, 25.2°C" in report
    assert "내일 일일 예보 (2026-08-05): 날씨 상태 비" in report
    assert "일 최대 강수확률 60%; 일 누적 강수량 3.2mm" in report
