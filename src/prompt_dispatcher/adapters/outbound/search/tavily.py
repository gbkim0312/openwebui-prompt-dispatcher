import httpx


class TavilySearch:
    def __init__(self, api_key: str, client: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client()

    def search(self, query: str, time_range: str = "week") -> tuple[tuple[str, str, str], ...]:
        if not self._api_key:
            raise ValueError("TAVILY_API_KEY is required for direct Tavily search")
        if time_range not in {"day", "week", "month", "year"}:
            raise ValueError("Tavily search period must be day, week, month, or year")
        response = self._client.post(
            "https://api.tavily.com/search",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "query": query,
                "topic": "news",
                "time_range": time_range,
                "search_depth": "basic",
                "max_results": 8,
            },
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json()
        records = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[tuple[str, str, str]] = []
        for item in records:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            published_date = str(item.get("published_date") or item.get("published_at") or "")
            content = str(item.get("content", ""))
            if published_date:
                content = f"발행일: {published_date}\n{content}"
            results.append((str(item.get("title", "")), str(item["url"]), content))
        return tuple(results)
