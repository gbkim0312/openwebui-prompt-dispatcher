from __future__ import annotations

from datetime import datetime
from math import hypot
from threading import Lock
from time import monotonic
from typing import Any, ClassVar
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx

from prompt_dispatcher.domain.job import AirQualitySource


class AirKorea:
    """AirKorea real-time and forecast adapter with a small in-process cache."""

    _station_url: ClassVar[str] = "https://apis.data.go.kr/B552584/MsrstnInfoInqireSvc/getMsrstnList"
    _realtime_url: ClassVar[str] = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMsrstnAcctoRltmMesureDnsty"
    _forecast_url: ClassVar[str] = "https://apis.data.go.kr/B552584/ArpltnInforInqireSvc/getMinuDustFrcstDspth"
    _portal_url: ClassVar[str] = "https://www.data.go.kr/data/15073861/openapi.do"

    def __init__(self, service_key: str, client: httpx.Client | None = None) -> None:
        self._service_key = service_key
        self._client = client or httpx.Client()
        self._lock = Lock()
        self._station_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._realtime_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._forecast_cache: tuple[float, list[dict[str, Any]]] | None = None

    def fetch(self, source: AirQualitySource) -> str:
        if not self._service_key:
            raise ValueError("AIRKOREA_SERVICE_KEY is required when AirKorea is enabled")
        station = self._station(source)
        lines = [
            f"{source.name} 에어코리아 대기질 데이터",
            f"측정소: {station.get('stationName', '측정소 미확인')} ({station.get('addr', '주소 미확인')})",
        ]
        if source.include_realtime:
            realtime = self._realtime(station["stationName"])
            lines.extend(self._format_realtime(realtime))
        if source.include_forecast:
            forecast = self._forecast()
            lines.extend(self._format_forecast(forecast))
        lines.append(f"출처: 한국환경공단 에어코리아 — {self._portal_url}")
        return "\n".join(lines)

    def _station(self, source: AirQualitySource) -> dict[str, Any]:
        key = f"{source.address or ''}|{source.station_name or ''}|{source.latitude}|{source.longitude}"
        with self._lock:
            cached = self._station_cache.get(key)
            if cached and cached[0] > monotonic():
                return cached[1]
        params: dict[str, str | int] = {"numOfRows": 100, "pageNo": 1}
        if source.station_name:
            params["stationName"] = source.station_name
        elif source.address:
            params["addr"] = source.address
        elif source.latitude is not None and source.longitude is not None:
            # The public station-list API searches by address/name.  The UI
            # always has a display region, so use it as a safe fallback when
            # only coordinates were stored in an older job.
            params["addr"] = source.name
        else:
            raise ValueError("AirKorea source requires address, station_name, or coordinates")
        items = self._request(self._station_url, params)
        if not items:
            raise ValueError(f"AirKorea station not found: {source.name}")
        selected = items[0]
        if source.latitude is not None and source.longitude is not None:
            def distance(item: dict[str, Any]) -> float:
                try:
                    return hypot(float(item["dmX"]) - source.latitude, float(item["dmY"]) - source.longitude)
                except (KeyError, TypeError, ValueError):
                    return float("inf")
            selected = min(items, key=distance)
        with self._lock:
            self._station_cache[key] = (monotonic() + 86400, selected)
        return selected

    def _realtime(self, station_name: str) -> dict[str, Any]:
        with self._lock:
            cached = self._realtime_cache.get(station_name)
            if cached and cached[0] > monotonic():
                return cached[1]
        items = self._request(
            self._realtime_url,
            {"stationName": station_name, "dataTerm": "DAILY", "ver": "1.0"},
        )
        if not items:
            raise ValueError(f"AirKorea realtime data not found: {station_name}")
        value = items[0]
        with self._lock:
            self._realtime_cache[station_name] = (monotonic() + 300, value)
        return value

    def _forecast(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._forecast_cache and self._forecast_cache[0] > monotonic():
                return self._forecast_cache[1]
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        items = self._request(
            self._forecast_url,
            {"searchDate": now.strftime("%Y-%m-%d"), "InformCode": "PM25"},
        )
        with self._lock:
            self._forecast_cache = (monotonic() + 1800, items)
        return items

    @staticmethod
    def _format_realtime(value: dict[str, Any]) -> list[str]:
        def v(key: str) -> str:
            raw = value.get(key)
            return "확인 불가" if raw in (None, "", "-") else str(raw)

        return [
            f"측정시각: {v('dataTime')}",
            f"PM10: {v('pm10Value')} μg/m³ (등급 {v('pm10Grade')})",
            f"PM2.5: {v('pm25Value')} μg/m³ (등급 {v('pm25Grade')})",
            f"오존(O₃): {v('o3Value')} ppm (등급 {v('o3Grade')})",
            f"이산화질소(NO₂): {v('no2Value')} ppm, 일산화탄소(CO): {v('coValue')} ppm, 아황산가스(SO₂): {v('so2Value')} ppm",
            f"통합대기환경지수: {v('khaiValue')} (등급 {v('khaiGrade')})",
        ]

    @staticmethod
    def _format_forecast(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["대기질 예보: 발표 자료 없음"]
        value = items[0]
        return [
            f"대기질 예보: {value.get('informData', '발표일 미확인')} / {value.get('informGrade', '등급 미확인')}",
            f"예보 내용: {value.get('informOverall', '내용 미확인')}",
        ]

    def _request(self, url: str, params: dict[str, str | int]) -> list[dict[str, Any]]:
        response = self._client.get(
            url,
            params={
                "serviceKey": unquote(self._service_key),
                "returnType": "json",
                **params,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        header = payload.get("response", {}).get("header", {})
        if str(header.get("resultCode", "00")) != "00":
            raise ValueError(f"AirKorea API error: {header.get('resultMsg', 'unknown error')}")
        body = payload.get("response", {}).get("body", {})
        raw = body.get("items", []) if isinstance(body, dict) else []
        if isinstance(raw, dict):
            raw = raw.get("item", [])
        if isinstance(raw, dict):
            return [raw]
        return raw if isinstance(raw, list) else []
