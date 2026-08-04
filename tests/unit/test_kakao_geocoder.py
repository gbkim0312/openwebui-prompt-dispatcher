import httpx

from prompt_dispatcher.adapters.outbound.geocoding.kakao import KakaoGeocoder


def test_kakao_geocoder_falls_back_to_keyword_search() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("address.json"):
            return httpx.Response(200, json={"documents": []})
        return httpx.Response(
            200,
            json={
                "documents": [
                    {
                        "place_name": "해운대구청",
                        "address_name": "부산광역시 해운대구 중동",
                        "x": "129.1636",
                        "y": "35.1631",
                    }
                ]
            },
        )

    values = KakaoGeocoder("test-key", httpx.Client(transport=httpx.MockTransport(handler))).search(
        "부산 해운대구"
    )

    assert len(requests) == 2
    assert requests[0].headers["Authorization"] == "KakaoAK test-key"
    assert values == [{"name": "부산광역시 해운대구 중동", "latitude": 35.1631, "longitude": 129.1636}]
