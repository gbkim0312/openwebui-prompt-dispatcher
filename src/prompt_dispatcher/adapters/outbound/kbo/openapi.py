import json
from datetime import date
from typing import ClassVar

import httpx

from prompt_dispatcher.domain.job import KboSource


class KboOpenApi:
    """Prompt-ready client for the locally hosted KBO results OpenAPI."""

    _paths: ClassVar[dict[str, str]] = {
        "latest_results": "/api/v1/results/latest",
        "games": "/api/v1/games",
        "rankings": "/api/v1/rankings",
        "player_stats": "/api/v1/player-stats",
    }

    def __init__(
        self, base_url: str, admin_api_key: str = "", client: httpx.Client | None = None
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._admin_api_key = admin_api_key
        self._client = client or httpx.Client()

    def fetch(self, source: KboSource, target_date: date) -> str:
        if source.data_type not in self._paths:
            raise ValueError(f"Unsupported KBO data type: {source.data_type}")
        if source.collect_before_fetch:
            self._collect(target_date)
        params: dict[str, str | int] = {"limit": source.limit}
        if source.team:
            params["team"] = source.team
        if source.data_type == "games":
            params["date"] = target_date.isoformat()
        elif source.data_type == "rankings":
            params = {"date": target_date.isoformat()}
        elif source.data_type == "player_stats":
            params["season"] = source.season or target_date.year
            params["role"] = source.role
            if source.team:
                params["team"] = source.team
        response = self._client.get(
            f"{self._base_url}{self._paths[source.data_type]}", params=params, timeout=30
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("KBO OpenAPI returned an invalid response")
        return "\n".join(
            (
                f"{source.name} KBO 공식 데이터",
                f"조회 종류: {source.data_type}; 기준 날짜: {target_date.isoformat()}",
                "아래 API 응답의 확인 가능한 사실만 사용하고, 없는 경기·기록·순위는 추정하지 마세요.",
                json.dumps(payload, ensure_ascii=False, indent=2),
                f"출처: KBO 경기 결과 OpenAPI — {response.url}",
            )
        )

    def test_connection(self) -> str:
        response = self._client.get(f"{self._base_url}/health/ready", timeout=10)
        response.raise_for_status()
        return response.text

    def _collect(self, target_date: date) -> None:
        if not self._admin_api_key:
            raise ValueError("KBO_ADMIN_API_KEY is required when collection refresh is enabled")
        response = self._client.post(
            f"{self._base_url}/internal/v1/collections",
            headers={"Authorization": f"Bearer {self._admin_api_key}"},
            json={"targetDate": target_date.isoformat(), "force": False},
            timeout=45,
        )
        response.raise_for_status()
