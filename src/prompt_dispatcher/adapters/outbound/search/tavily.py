import httpx


class TavilySearch:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client()

    def search(self, query: str) -> tuple[tuple[str, str, str], ...]:
        if not self._api_key:
            raise ValueError("TAVILY_API_KEY is required for direct Tavily search")
        response = self._client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={"query": query, "search_depth": "basic", "max_results": 8},
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("results", []) if isinstance(payload, dict) else []
        return tuple(
            (str(item.get("title", "")), str(item.get("url", "")), str(item.get("content", "")))
            for item in records
            if isinstance(item, dict) and item.get("url")
        )
