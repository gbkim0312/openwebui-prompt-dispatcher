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
    _warning_url: ClassVar[str] = "https://apis.data.go.kr/1360000/WthrWrnInfoService/getWthrWrnList"
    _mid_base_url: ClassVar[str] = "https://apis.data.go.kr/1360000/MidFcstInfoService"
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
        alert_service_key: str = "",
        mid_service_key: str = "",
    ) -> None:
        self._service_key = service_key
        self._alert_service_key = alert_service_key or service_key
        self._mid_service_key = mid_service_key or service_key
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
        # A KMA weather source is deliberately comprehensive.  The individual
        # public-data APIs are complementary (rather than alternative views of
        # the same data), so collect them all without asking a job author to
        # understand each endpoint.  A temporary failure in one service must
        # not discard the rest of the weather briefing.
        try:
            current = self._current(now, nx, ny)
            lines.append(
                f"현재 실황 ({current['time']}): {current['condition']}; "
                f"기온 {current.get('temperature', '-') }°C, "
                f"습도 {current.get('humidity', '-')}%, "
                f"1시간 강수량 {current.get('precipitation', '-')}, "
                f"바람 {current.get('wind_speed', '-')}m/s"
            )
        except Exception as error:
            lines.append(f"현재 실황: 조회 실패 ({type(error).__name__})")
        try:
            lines.extend(self._hourly(now, nx, ny))
        except Exception as error:
            lines.append(f"시간대별 초단기 예보: 조회 실패 ({type(error).__name__})")
        try:
            village_items = self._village_items(now, nx, ny)
            # The short-term service provides forecasts through the day after
            # tomorrow.  Keep all four calendar dates (today included) so it
            # fills the hand-off point before the mid-range forecast.
            for forecast in self._daily(village_items, max(source.forecast_days, 4)):
                lines.append(
                    f"일일 예보 ({forecast['date']}): 날씨 상태 {forecast['condition']}; "
                    f"최저 {forecast.get('min_temperature', '-')}°C, "
                    f"최고 {forecast.get('max_temperature', '-')}°C; "
                    f"일 최대 강수확률 {forecast.get('precipitation_probability', '-')}%"
                )
            lines.extend(self._later_today_hourly(now, village_items))
        except Exception as error:
            lines.append(f"단기 예보: 조회 실패 ({type(error).__name__})")
        try:
            lines.extend(self._alerts(now, source))
        except Exception as error:
            lines.append(f"기상특보: 조회 실패 ({type(error).__name__})")
        try:
            lines.extend(self._weekly(now))
        except Exception as error:
            lines.append(f"주간 예보: 조회 실패 ({type(error).__name__})")
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

    def _village_items(self, now: datetime, nx: int, ny: int) -> list[dict[str, Any]]:
        base = self._forecast_base(now)
        return self._request(
            "getVilageFcst", base.strftime("%Y%m%d"), base.strftime("%H00"), nx, ny, 1000
        )

    def _daily(self, items: list[dict[str, Any]], days: int) -> list[dict[str, str]]:
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

    def _later_today_hourly(self, now: datetime, items: list[dict[str, Any]]) -> list[str]:
        grouped: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        for item in items:
            date, time, category = item.get("fcstDate"), item.get("fcstTime"), item.get("category")
            if isinstance(date, str) and isinstance(time, str) and isinstance(category, str):
                grouped[(date, time)][category] = str(item.get("fcstValue", "-"))
        cutoff = (now + timedelta(hours=6)).strftime("%H%M")
        today = now.strftime("%Y%m%d")
        candidates = [
            ((date, time), values)
            for (date, time), values in sorted(grouped.items())
            if date == today and time >= cutoff
        ][:3]
        if not candidates:
            return []
        lines = ["시간대별 단기 예보 (초단기예보 이후):"]
        for (_, time), values in candidates:
            precipitation = self._number(values.get("PTY", "0"))
            condition = (
                self._precipitation_types.get(precipitation, "강수")
                if precipitation
                else self._sky_conditions.get(self._number(values.get("SKY", "0")), "알 수 없음")
            )
            lines.append(
                f"{time[:2]}:{time[2:]}: {condition}; 기온 {values.get('TMP', '-')}°C, "
                f"강수확률 {values.get('POP', '-')}%, 습도 {values.get('REH', '-')}%, "
                f"바람 {values.get('WSD', '-')}m/s"
            )
        return lines

    def _hourly(self, now: datetime, nx: int, ny: int) -> list[str]:
        base = self._ultra_forecast_base(now)
        items = self._request("getUltraSrtFcst", base.strftime("%Y%m%d"), base.strftime("%H%M"), nx, ny, 1000)
        grouped: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
        for item in items:
            date, time, category = item.get("fcstDate"), item.get("fcstTime"), item.get("category")
            if isinstance(date, str) and isinstance(time, str) and isinstance(category, str):
                grouped[(date, time)][category] = str(item.get("fcstValue", "-"))
        upcoming = sorted(grouped.items())[:6]
        if not upcoming:
            return ["시간대별 초단기 예보: 발표 자료 없음"]
        lines = [f"시간대별 초단기 예보 ({base.strftime('%Y-%m-%d %H:%M')} 발표):"]
        for (date, time), values in upcoming:
            precipitation = self._number(values.get("PTY", "0"))
            condition = (
                self._precipitation_types.get(precipitation, "강수")
                if precipitation
                else self._sky_conditions.get(self._number(values.get("SKY", "0")), "알 수 없음")
            )
            lines.append(
                f"{date[:4]}-{date[4:6]}-{date[6:]} {time[:2]}:{time[2:]}: {condition}; "
                f"기온 {values.get('T1H', '-')}°C, 강수확률 {values.get('POP', '-')}%, "
                f"습도 {values.get('REH', '-')}%, 바람 {values.get('WSD', '-')}m/s"
            )
        return lines

    def _alerts(self, now: datetime, source: WeatherSource) -> list[str]:
        """Return only warnings that can be attributed to the requested place.

        ``getWthrWrnList`` is a *bulletin list*, not a current-warning map.  In
        particular, a bulletin title can omit its affected area.  Treating every
        recent national bulletin as a warning for Seoul produced false alerts.
        Keep an unambiguous title only; an ambiguous bulletin must not influence
        the LLM's local weather briefing.
        """
        items = self._request_endpoint(
            self._warning_url,
            {
                "stnId": self._warning_station_id(source),
                "fromTmFc": (now - timedelta(days=1)).strftime("%Y%m%d"),
                "toTmFc": now.strftime("%Y%m%d"),
            },
            service_key=self._alert_service_key,
        )
        if not items:
            return [f"기상특보 ({source.name}): 최근 24시간 발표 목록 없음"]
        aliases = self._warning_region_aliases(source)
        applicable = [
            item
            for item in items
            if any(alias in str(item.get("title", "")) for alias in aliases)
        ]
        if not applicable:
            return [
                f"기상특보 ({source.name}): 최근 발표 목록에는 지역명이 명시된 {source.name} 특보가 없음. "
                "지역명이 없는 특보 제목은 해당 지역에 적용되는 것으로 사용하지 마세요."
            ]
        return [
            f"기상특보 ({source.name}, 지역명 확인됨): " + "; ".join(
                f"{item.get('title', '제목 없음')} ({item.get('tmFc', '발표시각 미제공')})"
                for item in applicable[:5]
            )
        ]

    @staticmethod
    def _warning_region_aliases(source: WeatherSource) -> tuple[str, ...]:
        """Known spellings that safely identify a warning's affected region."""
        name = source.name.strip()
        aliases = {name}
        for suffix in ("특별시", "광역시", "특별자치시", "특별자치도", "도", "시", "군", "구"):
            if name.endswith(suffix):
                aliases.add(name[: -len(suffix)])
        if "서울" in name:
            aliases.update({"서울", "서울특별시"})
        return tuple(alias for alias in aliases if len(alias) >= 2)

    @staticmethod
    def _warning_station_id(source: WeatherSource) -> int:
        """Use the capital-area warning office for Seoul and its vicinity.

        Station 108 is the national bulletin feed; 109 is the Seoul/Incheon/
        Gyeonggi office.  This narrows the candidate bulletin set, while the
        title check above remains the actual guard against false attribution.
        """
        if "서울" in source.name or (37.0 <= source.latitude <= 38.1 and 126.0 <= source.longitude <= 127.8):
            return 109
        return 108

    def _weekly(self, now: datetime) -> list[str]:
        base = self._mid_base(now).strftime("%Y%m%d%H%M")
        land = self._request_endpoint(
            f"{self._mid_base_url}/getMidLandFcst",
            {"regId": "11B00000", "tmFc": base},
            service_key=self._mid_service_key,
        )
        temperature = self._request_endpoint(
            f"{self._mid_base_url}/getMidTa",
            {"regId": "11B10101", "tmFc": base},
            service_key=self._mid_service_key,
        )
        if not land or not temperature:
            return ["주간 예보 (서울): 발표 자료 없음"]
        weather, temperatures = land[0], temperature[0]
        lines = [
            f"주간 예보 (서울, {base} 발표):",
            "| 날짜 | 날씨 (오전 / 오후) | 강수확률 (오전 / 오후) | 최저 | 최고 |",
            "|---|---|---|---:|---:|",
        ]
        for day in range(3, 8):
            weather_am = self._first_present(weather.get(f"wf{day}Am"), weather.get(f"wf{day}"))
            weather_pm = self._first_present(weather.get(f"wf{day}Pm"), weather.get(f"wf{day}"))
            rain_am = self._first_present(weather.get(f"rnSt{day}Am"), weather.get(f"rnSt{day}"))
            rain_pm = self._first_present(weather.get(f"rnSt{day}Pm"), weather.get(f"rnSt{day}"))
            minimum = self._first_present(temperatures.get(f"taMin{day}"))
            maximum = self._first_present(temperatures.get(f"taMax{day}"))
            date = (now.date() + timedelta(days=day)).isoformat()
            lines.append(
                f"| {date} ({day}일 후) | {weather_am} / {weather_pm} | "
                f"{rain_am}% / {rain_pm}% | {minimum}°C | {maximum}°C |"
            )
        return lines

    def _request(
        self, endpoint: str, base_date: str, base_time: str, nx: int, ny: int, rows: int = 100
    ) -> list[dict[str, Any]]:
        return self._request_endpoint(
            f"{self._base_url}/{endpoint}",
            {"base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny},
            rows,
        )

    def _request_endpoint(
        self,
        url: str,
        parameters: dict[str, str | int],
        rows: int = 100,
        service_key: str | None = None,
    ) -> list[dict[str, Any]]:
        response = self._client.get(
            url,
            params={
                "serviceKey": unquote(service_key or self._service_key),
                "pageNo": 1,
                "numOfRows": rows,
                "dataType": "JSON",
                **parameters,
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

    @staticmethod
    def _mid_base(now: datetime) -> datetime:
        ready = now - timedelta(minutes=30)
        if ready.hour >= 18:
            return ready.replace(hour=18, minute=0, second=0, microsecond=0)
        if ready.hour >= 6:
            return ready.replace(hour=6, minute=0, second=0, microsecond=0)
        return (ready - timedelta(days=1)).replace(hour=18, minute=0, second=0, microsecond=0)

    @classmethod
    def _forecast_base(cls, now: datetime) -> datetime:
        ready = now - timedelta(minutes=10)
        for hour in (23, 20, 17, 14, 11, 8, 5, 2):
            candidate = ready.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate <= ready:
                return candidate
        return (ready - timedelta(days=1)).replace(hour=23, minute=0, second=0, microsecond=0)

    @staticmethod
    def _ultra_forecast_base(now: datetime) -> datetime:
        ready = now - timedelta(minutes=45)
        if ready.minute < 30:
            ready -= timedelta(hours=1)
        return ready.replace(minute=30, second=0, microsecond=0)

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

    @staticmethod
    def _first_present(*values: object) -> str:
        for value in values:
            if value is not None and value != "":
                return str(value)
        return "-"

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
