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
                    "temperature_2m": 25.2,
                    "apparent_temperature": 26.1,
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
                },
            },
        )

    weather = OpenMeteoWeather(httpx.Client(transport=httpx.MockTransport(handler)))
    report = weather.fetch(WeatherSource("seoul", "서울", 37.5665, 126.9780))

    assert captured["timezone"] == "Asia/Seoul"
    assert "현재: 맑음, 25.2°C" in report
    assert "내일 (2026-08-05): 비" in report
