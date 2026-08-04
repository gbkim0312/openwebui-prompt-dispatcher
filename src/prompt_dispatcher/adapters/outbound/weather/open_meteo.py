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
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
        }
        if source.include_current:
            params["current"] = (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "weather_code,precipitation,wind_speed_10m"
            )
        if source.include_daily:
            params["daily"] = (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_probability_max,precipitation_sum"
            )
        response = self._client.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=30)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("Open-Meteo returned an invalid response")
        lines = [
            f"{source.name} 날씨 데이터",
            (
                "데이터 해석 규칙: 현재 수치와 일일 예보를 혼동하지 마세요. "
                "날씨 상태는 강수확률이 아니며, 강수확률은 명시된 % 값만 그대로 사용하세요. "
                "제공되지 않은 시간대별 수치나 확률은 추정하지 마세요."
            ),
        ]
        current = payload.get("current")
        if source.include_current and isinstance(current, dict):
            condition = self._condition(current.get("weather_code"))
            lines.append(
                f"현재 ({current.get('time', '시각 미제공')}): "
                f"{condition}, {current.get('temperature_2m')}°C "
                f"(체감 {current.get('apparent_temperature')}°C), "
                f"습도 {current.get('relative_humidity_2m')}%, "
                f"강수량 {current.get('precipitation')}mm, "
                f"바람 {current.get('wind_speed_10m')}km/h"
            )
        daily = payload.get("daily")
        if source.include_daily and isinstance(daily, dict):
            dates = daily.get("time", [])
            for index, date in enumerate(dates[: source.forecast_days]):
                if not isinstance(date, str):
                    continue
                prefix = "오늘" if index == 0 else "내일" if index == 1 else date
                lines.append(
                    f"{prefix} 일일 예보 ({date}): "
                    f"날씨 상태 {self._condition(self._at(daily, 'weather_code', index))}; "
                    f"최저 {self._at(daily, 'temperature_2m_min', index)}°C, "
                    f"최고 {self._at(daily, 'temperature_2m_max', index)}°C; "
                    f"일 최대 강수확률 {self._at(daily, 'precipitation_probability_max', index)}%; "
                    f"일 누적 강수량 {self._at(daily, 'precipitation_sum', index)}mm"
                )
        lines.append(f"기준 시각: {datetime.now(ZoneInfo(source.timezone)).isoformat(timespec='minutes')}")
        lines.append(f"출처: Open-Meteo — {response.url}")
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
