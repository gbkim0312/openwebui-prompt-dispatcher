from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from math import cos, floor, log, pi, pow, sin, tan
from typing import Any, ClassVar
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx

from prompt_dispatcher.domain.job import WeatherSource


class KmaWeather:
    """Korea Meteorological Administration village forecast adapter.

    Uses the public-data portal's short-term forecast service: ultra-short-term
    observations for current conditions and village forecasts for daily values.
    """

    _base_url: ClassVar[str] = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0"
    _portal_url: ClassVar[str] = "https://www.data.go.kr/data/15084084/openapi.do"
    _precipitation_types: ClassVar[dict[int, str]] = {
        0: "없음", 1: "비", 2: "비/눈", 3: "눈", 5: "빗방울", 6: "빗방울/눈날림", 7: "눈날림"
    }
    _sky_conditions: ClassVar[dict[int, str]] = {1: "맑음", 3: "구름많음", 4: "흐림"}

    def __init__(
        self,
        service_key: str,
        client: httpx.Client | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._service_key = service_key
        self._client = client or httpx.Client()
        self._now = now or (lambda: datetime.now(ZoneInfo("Asia/Seoul")))

    def fetch(self, source: WeatherSource) -> str:
        if not self._service_key:
            raise ValueError("KMA_SERVICE_KEY is required when the weather engine is KMA")
        now = self._now().astimezone(ZoneInfo("Asia/Seoul"))
        nx, ny = self._to_grid(source.latitude, source.longitude)
        lines = [
            f"{source.name} 기상청 날씨 데이터",
            (
                "데이터 해석 규칙: 현재 실황과 일일 예보를 혼동하지 마세요. "
                "강수확률은 명시된 % 값만 사용하고, 날씨 상태를 확률로 바꾸지 마세요."
            ),
        ]
        if source.include_current:
            current = self._current(now, nx, ny)
            lines.append(
                f"현재 실황 ({current['time']}): {current['condition']}; "
                f"기온 {current.get('temperature', '-') }°C, "
                f"습도 {current.get('humidity', '-')}%, "
                f"1시간 강수량 {current.get('precipitation', '-')}, "
                f"바람 {current.get('wind_speed', '-')}m/s"
            )
        if source.include_daily:
            for forecast in self._daily(now, nx, ny, source.forecast_days):
                lines.append(
                    f"일일 예보 ({forecast['date']}): 날씨 상태 {forecast['condition']}; "
                    f"최저 {forecast.get('min_temperature', '-')}°C, "
                    f"최고 {forecast.get('max_temperature', '-')}°C; "
                    f"일 최대 강수확률 {forecast.get('precipitation_probability', '-')}%"
                )
        lines.append(f"기준 시각: {now.isoformat(timespec='minutes')}")
        lines.append(f"출처: 기상청 단기예보 조회서비스 — {self._portal_url}")
        return "\n".join(lines)

    def _current(self, now: datetime, nx: int, ny: int) -> dict[str, str]:
        base = (now - timedelta(minutes=45)).replace(minute=0, second=0, microsecond=0)
        items = self._request("getUltraSrtNcst", base.strftime("%Y%m%d"), base.strftime("%H00"), nx, ny)
        values = {str(item.get("category")): str(item.get("obsrValue", "-")) for item in items}
        precipitation_type = self._number(values.get("PTY", "0"))
        return {
            "time": f"{base.strftime('%Y-%m-%d %H:%M')} 발표",
            "condition": (
                "강수 없음"
                if precipitation_type == 0
                else self._precipitation_types.get(precipitation_type, "알 수 없음")
            ),
            "temperature": values.get("T1H", "-"),
            "humidity": values.get("REH", "-"),
            "precipitation": values.get("RN1", "-"),
            "wind_speed": values.get("WSD", "-"),
        }

    def _daily(self, now: datetime, nx: int, ny: int, days: int) -> list[dict[str, str]]:
        base = self._forecast_base(now)
        items = self._request("getVilageFcst", base.strftime("%Y%m%d"), base.strftime("%H00"), nx, ny, 1000)
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in items:
            date = item.get("fcstDate")
            if isinstance(date, str):
                grouped[date].append(item)
        forecasts: list[dict[str, str]] = []
        for date in sorted(grouped)[:days]:
            values = grouped[date]
            by_category: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for item in values:
                by_category[str(item.get("category"))].append(item)
            condition = self._forecast_condition(by_category)
            forecasts.append(
                {
                    "date": f"{date[:4]}-{date[4:6]}-{date[6:]}",
                    "condition": condition,
                    "min_temperature": self._first_value(by_category.get("TMN", [])),
                    "max_temperature": self._first_value(by_category.get("TMX", [])),
                    "precipitation_probability": self._max_value(by_category.get("POP", [])),
                }
            )
        return forecasts

    def _request(
        self, endpoint: str, base_date: str, base_time: str, nx: int, ny: int, rows: int = 100
    ) -> list[dict[str, Any]]:
        response = self._client.get(
            f"{self._base_url}/{endpoint}",
            params={
                # data.go.kr presents the same general key in encoded and
                # decoded forms.  httpx encodes query parameters itself, so
                # normalize either form to decoded text before handing it over.
                "serviceKey": unquote(self._service_key),
                "pageNo": 1,
                "numOfRows": rows,
                "dataType": "JSON",
                "base_date": base_date,
                "base_time": base_time,
                "nx": nx,
                "ny": ny,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("KMA returned an invalid response")
        body = payload.get("response", {}).get("body", {}) if isinstance(payload.get("response"), dict) else {}
        header = payload.get("response", {}).get("header", {}) if isinstance(payload.get("response"), dict) else {}
        if str(header.get("resultCode", "00")) != "00":
            raise ValueError(f"KMA API error: {header.get('resultMsg', 'unknown error')}")
        items = body.get("items", {}).get("item", []) if isinstance(body, dict) else []
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    @classmethod
    def _forecast_base(cls, now: datetime) -> datetime:
        ready = now - timedelta(minutes=10)
        for hour in (23, 20, 17, 14, 11, 8, 5, 2):
            candidate = ready.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate <= ready:
                return candidate
        return (ready - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)

    @classmethod
    def _forecast_condition(cls, values: dict[str, list[dict[str, Any]]]) -> str:
        precipitation = cls._number(cls._value_near_noon(values.get("PTY", [])))
        if precipitation:
            return cls._precipitation_types.get(precipitation, "강수")
        sky = cls._number(cls._value_near_noon(values.get("SKY", [])))
        return cls._sky_conditions.get(sky, "알 수 없음")

    @staticmethod
    def _first_value(items: list[dict[str, Any]]) -> str:
        return str(items[0].get("fcstValue", "-")) if items else "-"

    @classmethod
    def _max_value(cls, items: list[dict[str, Any]]) -> str:
        values = [cls._number(str(item.get("fcstValue", ""))) for item in items]
        return str(max(values)) if values else "-"

    @staticmethod
    def _value_near_noon(items: list[dict[str, Any]]) -> str:
        if not items:
            return "0"
        item = min(items, key=lambda value: abs(int(str(value.get("fcstTime", "1200"))[:2]) - 12))
        return str(item.get("fcstValue", "0"))

    @staticmethod
    def _number(value: str) -> int:
        try:
            return int(float(value))
        except ValueError:
            return 0

    @staticmethod
    def _to_grid(latitude: float, longitude: float) -> tuple[int, int]:
        re, grid, slat1, slat2, olon, olat, xo, yo = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43.0, 136.0
        degrad = pi / 180.0
        re /= grid
        slat1 *= degrad
        slat2 *= degrad
        olon *= degrad
        olat *= degrad
        sn = tan(pi * 0.25 + slat2 * 0.5) / tan(pi * 0.25 + slat1 * 0.5)
        sn = log(cos(slat1) / cos(slat2)) / log(sn)
        sf = pow(tan(pi * 0.25 + slat1 * 0.5), sn) * cos(slat1) / sn
        ro = re * sf / pow(tan(pi * 0.25 + olat * 0.5), sn)
        ra = re * sf / pow(tan(pi * 0.25 + latitude * degrad * 0.5), sn)
        theta = longitude * degrad - olon
        if theta > pi:
            theta -= 2.0 * pi
        if theta < -pi:
            theta += 2.0 * pi
        theta *= sn
        return floor(ra * sin(theta) + xo + 0.5), floor(ro - ra * cos(theta) + yo + 0.5)
