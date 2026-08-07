from __future__ import annotations

import json
from typing import Any

import httpx

from prompt_dispatcher.domain.job import JobCollectorSource


class JobCollectorClient:
    """Small client for the read-only Job Collector profile API."""

    def __init__(
        self,
        base_url: str,
        admin_api_key: str = "",
        timeout: float = 15.0,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_api_key = admin_api_key
        self.timeout = timeout
        self._client = client

    def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        if self._client is not None:
            return self._client.get(f"{self.base_url}{path}", **kwargs)
        return httpx.get(f"{self.base_url}{path}", **kwargs)

    def list_profiles(self) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.admin_api_key}"} if self.admin_api_key else {}
        response = self._get("/api/v1/profiles", headers=headers, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("Job Collector profile response must contain a list")
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    def test_connection(self) -> list[dict[str, Any]]:
        return self.list_profiles()

    def fetch(self, source: JobCollectorSource) -> str:
        """Fetch only already-collected postings and format them for a research task."""
        employment_aliases = {
            "정규직": "FULL_TIME",
            "계약직": "CONTRACT",
            "시간제": "PART_TIME",
            "인턴": "INTERN",
            "파견직": "DISPATCH",
            "프리랜서": "FREELANCE",
            "기타": "OTHER",
        }
        params: dict[str, str | int] = {"limit": source.limit, "sort": source.sort}
        scalar_filters = {
            "profile_id": source.profile_id,
            "keyword": source.keyword,
            "region": source.region,
            "min_experience": source.min_experience,
            "max_experience": source.max_experience,
        }
        params.update({key: value for key, value in scalar_filters.items() if value not in (None, "")})
        list_filters = {
            "sources": source.sources,
            "statuses": source.statuses,
            "categories": source.categories,
            "skills": source.skills,
            "employment_types": tuple(
                employment_aliases.get(value, value.upper()) for value in source.employment_types
            ),
            "experience_types": source.experience_types,
        }
        params.update(
            {key: ",".join(values) for key, values in list_filters.items() if values}
        )
        headers = {"Authorization": f"Bearer {self.admin_api_key}"} if self.admin_api_key else {}
        response = self._get(
            "/api/v1/jobs", params=params, headers=headers, timeout=self.timeout
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = response.text.strip().replace("\n", " ")[:500]
            raise RuntimeError(
                f"Job Collector API returned HTTP {response.status_code} for {response.url}"
                + (f": {body}" if body else "")
            ) from exc
        payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
            raise ValueError("Job Collector jobs response must contain an items list")
        return "\n".join(
            (
                f"{source.name} 채용 공고 데이터",
                "아래 API 응답의 확인 가능한 공고만 사용하고, 없는 자격·마감일·근무 조건은 추정하지 마세요.",
                "이 데이터는 이미 수집·저장된 공고 조회 결과이며, 이 리서치에서 외부 채용 사이트 동기화는 실행하지 않습니다.",
                json.dumps(payload, ensure_ascii=False, indent=2),
                f"출처: Job Collector OpenAPI — {response.url}",
            )
        )
