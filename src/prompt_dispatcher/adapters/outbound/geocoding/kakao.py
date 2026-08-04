from typing import Any

import httpx


class KakaoGeocoder:
    """Small server-side wrapper for Kakao's Korean address/place search API."""

    _address_url = "https://dapi.kakao.com/v2/local/search/address.json"
    _keyword_url = "https://dapi.kakao.com/v2/local/search/keyword.json"

    def __init__(self, rest_api_key: str, client: httpx.Client | None = None) -> None:
        self._key = rest_api_key
        self._client = client or httpx.Client()

    def search(self, query: str) -> list[dict[str, str | float]]:
        if not self._key:
            raise ValueError("KAKAO_REST_API_KEY is required for location search")
        text = query.strip()
        if not text:
            return []
        documents = self._request(self._address_url, text)
        if not documents:
            documents = self._request(self._keyword_url, text)
        values: list[dict[str, str | float]] = []
        for document in documents:
            try:
                longitude, latitude = float(document["x"]), float(document["y"])
            except (KeyError, TypeError, ValueError):
                continue
            name = str(
                document.get("road_address_name")
                or document.get("address_name")
                or document.get("place_name")
                or "검색 결과"
            )
            values.append({"name": name, "latitude": latitude, "longitude": longitude})
        return values[:10]

    def _request(self, url: str, query: str) -> list[dict[str, Any]]:
        response = self._client.get(
            url,
            params={"query": query, "size": 10},
            headers={"Authorization": f"KakaoAK {self._key}"},
            timeout=10,
        )
        response.raise_for_status()
        payload = response.json()
        documents = payload.get("documents", []) if isinstance(payload, dict) else []
        return [item for item in documents if isinstance(item, dict)]
