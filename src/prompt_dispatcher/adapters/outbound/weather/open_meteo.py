from datetime import datetime
from typing import ClassVar
from zoneinfo import ZoneInfo

import httpx

from prompt_dispatcher.domain.job import WeatherSource


class OpenMeteoWeather:
    """Small Open-Meteo adapter that produces prompt-ready Korean weather text."""

    _codes: ClassVar[dict[int, str]] = {
        0: "맑음", 1: "대체로 맑음", 2: "부분적으로 흐림", 3: "흐림", 45: "안개",
        48: "서리 안개", 51: "이슬비", 53: "이슬비", 55: "강한 이슬비", 61: "비",
        63: "비", 65: "강한 비", 71: "눈", 73: "눈", 75: "강한 눈", 80: "소나기",
        81: "소나기", 82: "강한 소나기", 95: "뇌우",
    }

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client or httpx.Client()

    def fetch(self, source: WeatherSource) -> str:
        params: dict[str, str | int | float] = {
            "latitude": source.latitude,
            "longitude": source.longitude,
            "timezone": source.timezone,
            "forecast_days": source.forecast_days,
        }
        if source.include_current:
            params["current"] = "temperature_2m,apparent_temperature,weather_code,precipitation,wind_speed_10m"
        if source.include_daily:
            params["daily"] = "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        response = self._client.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Open-Meteo returned an invalid response")
        lines = [f"{source.name} 날씨"]
        current = payload.get("current")
        if source.include_current and isinstance(current, dict):
            condition = self._condition(current.get("weather_code"))
            lines.append(
                "현재: "
                f"{condition}, {current.get('temperature_2m')}°C "
                f"(체감 {current.get('apparent_temperature')}°C), "
                f"강수 {current.get('precipitation')}mm, 바람 {current.get('wind_speed_10m')}km/h"
            )
        daily = payload.get("daily")
        if source.include_daily and isinstance(daily, dict):
            dates = daily.get("time", [])
            for index, date in enumerate(dates[: source.forecast_days]):
                if not isinstance(date, str):
                    continue
                prefix = "오늘" if index == 0 else "내일" if index == 1 else date
                lines.append(
                    f"{prefix} ({date}): {self._condition(self._at(daily, 'weather_code', index))}, "
                    f"{self._at(daily, 'temperature_2m_min', index)}~{self._at(daily, 'temperature_2m_max', index)}°C, "
                    f"강수확률 {self._at(daily, 'precipitation_probability_max', index)}%"
                )
        lines.append(f"기준 시각: {datetime.now(ZoneInfo(source.timezone)).isoformat(timespec='minutes')}")
        return "\n".join(lines)

    def _condition(self, value: object) -> str:
        try:
            if not isinstance(value, int | float | str):
                return "알 수 없음"
            return self._codes.get(int(value), "알 수 없음")
        except (TypeError, ValueError):
            return "알 수 없음"

    @staticmethod
    def _at(data: dict[str, object], key: str, index: int) -> object:
        values = data.get(key, [])
        return values[index] if isinstance(values, list) and index < len(values) else "-"
