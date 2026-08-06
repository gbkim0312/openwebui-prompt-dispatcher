from __future__ import annotations

from typing import Any

import httpx


class JobCollectorClient:
    """Small client for the read-only Job Collector profile API."""

    def __init__(self, base_url: str, admin_api_key: str = "", timeout: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.admin_api_key = admin_api_key
        self.timeout = timeout

    def list_profiles(self) -> list[dict[str, Any]]:
        headers = {"Authorization": f"Bearer {self.admin_api_key}"} if self.admin_api_key else {}
        response = httpx.get(
            f"{self.base_url}/api/v1/profiles", headers=headers, timeout=self.timeout
        )
        response.raise_for_status()
        payload = response.json()
        items = payload.get("items", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("Job Collector profile response must contain a list")
        return [item for item in items if isinstance(item, dict) and item.get("id")]

    def test_connection(self) -> list[dict[str, Any]]:
        return self.list_profiles()
