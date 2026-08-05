import json
from dataclasses import replace
from datetime import date, timedelta
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
        "teams": "/api/v1/teams",
        "awards": "/api/v1/awards",
        "game_details": "/api/v1/games/{game_id}/details",
        "lineups": "/api/v1/games/{game_id}/lineups",
        "analysis": "/api/v1/games/{game_id}/analysis",
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
        if source.data_type in {"game_details", "lineups", "analysis"} and not source.game_id:
            source = replace(source, game_id=self._resolve_game_id(source, target_date))
        if source.collect_before_fetch:
            self._collect(source, target_date)
        params: dict[str, str | int] = {"limit": source.limit}
        if source.team:
            params["team"] = source.team
        if source.data_type == "games":
            if source.range_days == 1:
                params["date"] = target_date.isoformat()
            else:
                params["from"] = (target_date - timedelta(days=source.range_days - 1)).isoformat()
                params["to"] = target_date.isoformat()
            if source.status:
                params["status"] = source.status
            if source.league_type:
                params["leagueType"] = source.league_type
        elif source.data_type == "rankings":
            params = {"date": target_date.isoformat()}
        elif source.data_type == "player_stats":
            params["season"] = source.season or target_date.year
            params["role"] = source.role
            if source.team:
                params["team"] = source.team
        elif source.data_type == "awards":
            params = {"season": source.season or target_date.year}
        elif source.data_type == "teams":
            params = {}
        if source.data_type in {"game_details", "lineups", "analysis"}:
            if not source.game_id:
                raise ValueError(f"KBO game_id is required for {source.data_type}")
            params = {}
        path = self._paths[source.data_type].format(game_id=source.game_id)
        response = self._client.get(
            f"{self._base_url}{path}", params=params, timeout=30
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise TypeError("KBO OpenAPI returned an invalid response")
        return "\n".join(
            (
                f"{source.name} KBO 공식 데이터",
                f"조회 종류: {source.data_type}; 기준 날짜: {target_date.isoformat()}",
                f"선택 경기 ID: {source.game_id}" if source.game_id else "",
                "아래 API 응답의 확인 가능한 사실만 사용하고, 없는 경기·기록·순위는 추정하지 마세요.",
                json.dumps(payload, ensure_ascii=False, indent=2),
                f"출처: KBO 경기 결과 OpenAPI — {response.url}",
            )
        )

    def _resolve_game_id(self, source: KboSource, target_date: date) -> int:
        if not source.team:
            raise ValueError("경기 ID를 입력하거나 팀을 선택하세요.")
        if source.data_type in {"lineups", "analysis"}:
            response = self._client.get(
                f"{self._base_url}/api/v1/games",
                params={"date": target_date.isoformat(), "team": source.team, "limit": 20},
                timeout=30,
            )
            response.raise_for_status()
            payload = response.json()
            games = payload.get("games", []) if isinstance(payload, dict) else []
            if isinstance(games, list):
                for game in games:
                    if isinstance(game, dict) and isinstance(game.get("id"), int):
                        return int(game["id"])
        response = self._client.get(
            f"{self._base_url}/api/v1/results/latest",
            params={"team": source.team, "limit": 1},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        games = payload.get("games", []) if isinstance(payload, dict) else []
        if isinstance(games, list) and games and isinstance(games[0], dict):
            game_id = games[0].get("id")
            if isinstance(game_id, int):
                return game_id
        raise ValueError(f"팀 {source.team}의 조회 가능한 경기를 찾지 못했습니다.")

    def test_connection(self) -> str:
        response = self._client.get(f"{self._base_url}/health/ready", timeout=10)
        response.raise_for_status()
        return response.text

    def _collect(self, source: KboSource, target_date: date) -> None:
        if not self._admin_api_key:
            raise ValueError("KBO_ADMIN_API_KEY is required when collection refresh is enabled")
        headers = {"Authorization": f"Bearer {self._admin_api_key}"}
        if source.data_type in {"rankings", "player_stats", "awards"}:
            response = self._client.post(
                f"{self._base_url}/internal/v1/records/collect", headers=headers, timeout=45
            )
        elif source.data_type in {"game_details", "lineups", "analysis"}:
            if not source.game_id:
                raise ValueError(f"KBO game_id is required for {source.data_type} collection")
            suffix = "details/collect" if source.data_type == "game_details" else "preview/collect"
            response = self._client.post(
                f"{self._base_url}/internal/v1/games/{source.game_id}/{suffix}",
                headers=headers,
                timeout=45,
            )
        else:
            response = self._client.post(
                f"{self._base_url}/internal/v1/collections",
                headers=headers,
                json={"targetDate": target_date.isoformat(), "force": False},
                timeout=45,
            )
        response.raise_for_status()
