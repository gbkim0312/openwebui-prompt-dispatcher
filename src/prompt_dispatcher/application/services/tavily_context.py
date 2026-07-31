from prompt_dispatcher.adapters.outbound.search.tavily import TavilySearch

TAVILY_TOOL_ID = "web_search_with_tavily"


def enrich_with_tavily(
    prompt: str,
    tool_ids: tuple[str, ...],
    tavily: TavilySearch | None,
    time_range: str = "week",
    search_query: str | None = None,
    topic: str = "news",
    search_depth: str = "basic",
    max_results: int = 8,
    include_domains: tuple[str, ...] = (),
    exclude_domains: tuple[str, ...] = (),
) -> tuple[str, tuple[str, ...]]:
    if TAVILY_TOOL_ID not in tool_ids:
        return prompt, tool_ids
    if tavily is None:
        raise ValueError("TAVILY_API_KEY is required for Web Search with Tavily")
    results = tavily.search(
        search_query or prompt,
        time_range,
        topic,
        search_depth,
        max_results,
        include_domains,
        exclude_domains,
    )
    sources = "\n\n".join(
        f"[{index}] {title}\nURL: {url}\n내용: {content}"
        for index, (title, url, content) in enumerate(results, start=1)
    )
    enriched = (
        f"{prompt}\n\n아래는 Tavily가 수집한 최신 검색 결과입니다. "
        f"최근 { {'day': '1일', 'week': '7일', 'month': '1개월', 'year': '1년'}[time_range] } "
        "이내에 발행 또는 갱신된 결과만 근거로 답변하고, "
        "확인 가능한 날짜와 출처 URL을 각 항목에 포함하세요. 결과가 부족하면 "
        "오래된 자료로 채우지 말고 부족한 개수를 명시하세요.\n\n"
        f"--- 검색 결과 ---\n{sources}"
    )
    return enriched, tuple(tool_id for tool_id in tool_ids if tool_id != TAVILY_TOOL_ID)
