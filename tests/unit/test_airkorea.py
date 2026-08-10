import httpx
import pytest

from prompt_dispatcher.adapters.outbound.weather.airkorea import AirKorea
from prompt_dispatcher.domain.job import AirQualitySource


def test_airkorea_selects_nearest_station_and_formats_data() -> None:
    calls: list[str] = []

    def response(items: list[dict[str, object]]) -> httpx.Response:
        return httpx.Response(
            200,
            json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}},
        )

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("getMsrstnList"):
            assert request.url.params["addr"] == "서울"
            return response(
                [
                    {"stationName": "강남구", "addr": "서울 강남구", "dmX": "37.51", "dmY": "127.04"},
                    {"stationName": "종로구", "addr": "서울 종로구", "dmX": "37.57", "dmY": "127.00"},
                ]
            )
        if request.url.path.endswith("getMsrstnAcctoRltmMesureDnsty"):
            assert request.url.params["stationName"] == "종로구"
            return response(
                [{
                    "dataTime": "2026-08-10 08:00",
                    "pm10Value": "18", "pm25Value": "9", "o3Value": "0.021",
                    "no2Value": "0.014", "coValue": "0.3", "so2Value": "0.002",
                    "khaiValue": "42", "khaiGrade": "2", "pm10Grade": "1", "pm25Grade": "1", "o3Grade": "1",
                }]
            )
        if request.url.path.endswith("getMinuDustFrcstDspth"):
            return response([{"informData": "2026-08-10", "informGrade": "서울: 보통", "informOverall": "전국 보통"}])
        return response([])

    adapter = AirKorea("service-key", httpx.Client(transport=httpx.MockTransport(handler)))
    report = adapter.fetch(AirQualitySource("seoul", "서울", address="서울", latitude=37.5665, longitude=126.9780))

    assert "측정소: 종로구" in report
    assert "PM10: 18 μg/m³" in report
    assert "PM2.5: 9 μg/m³" in report
    assert "대기질 예보: 2026-08-10 / 서울: 보통" in report
    assert len(calls) == 3


def test_airkorea_reuses_station_and_realtime_cache() -> None:
    count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal count
        count += 1
        if request.url.path.endswith("getMsrstnList"):
            items = [{"stationName": "종로구", "addr": "서울", "dmX": "37.57", "dmY": "127.00"}]
        elif request.url.path.endswith("getMsrstnAcctoRltmMesureDnsty"):
            items = [{"dataTime": "2026-08-10 08:00", "pm10Value": "18"}]
        else:
            items = []
        return httpx.Response(200, json={"response": {"header": {"resultCode": "00"}, "body": {"items": {"item": items}}}})

    adapter = AirKorea("service-key", httpx.Client(transport=httpx.MockTransport(handler)))
    source = AirQualitySource("seoul", "서울", address="서울", latitude=37.5665, longitude=126.9780, include_forecast=False)
    adapter.fetch(source)
    adapter.fetch(source)

    assert count == 2


def test_airkorea_accepts_list_items_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("getMsrstnList"):
            items = [{"stationName": "종로구", "addr": "서울", "dmX": "37.57", "dmY": "127.00"}]
        elif request.url.path.endswith("getMsrstnAcctoRltmMesureDnsty"):
            items = [{"dataTime": "2026-08-10 08:00", "pm10Value": "18"}]
        else:
            items = []
        return httpx.Response(
            200,
            json={"response": {"header": {"resultCode": "00"}, "body": {"items": items}}},
        )

    adapter = AirKorea("service-key", httpx.Client(transport=httpx.MockTransport(handler)))
    source = AirQualitySource(
        "seoul-list", "서울", address="서울", latitude=37.5665, longitude=126.9780, include_forecast=False
    )

    report = adapter.fetch(source)

    assert "측정소: 종로구" in report
    assert "PM10: 18 μg/m³" in report


def test_airkorea_does_not_expose_service_key_in_http_error() -> None:
    adapter = AirKorea(
        "secret-service-key",
        httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(401))),
    )
    source = AirQualitySource("seoul", "서울", address="서울", include_forecast=False)

    with pytest.raises(ValueError, match=r"HTTP 401") as error:
        adapter.fetch(source)

    assert "secret-service-key" not in str(error.value)


def test_airkorea_lists_station_catalogue_with_disambiguating_address() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["numOfRows"] == "10000"
        return httpx.Response(
            200,
            json={
                "response": {
                    "header": {"resultCode": "00"},
                    "body": {
                        "items": {
                            "item": [
                                {"stationName": "중구", "addr": "대구광역시 중구", "dmX": "35.86", "dmY": "128.60"},
                                {"stationName": "중구", "addr": "서울특별시 중구", "dmX": "37.56", "dmY": "126.97"},
                            ]
                        }
                    },
                }
            },
        )

    adapter = AirKorea("service-key", httpx.Client(transport=httpx.MockTransport(handler)))

    stations = adapter.list_stations()

    assert stations[0]["label"] == "대구광역시 중구 · 중구"
    assert stations[1]["label"] == "서울특별시 중구 · 중구"
    assert stations[1]["latitude"] == 37.56
