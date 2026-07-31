from prompt_dispatcher.adapters.outbound.search.tavily import TavilySearch

TAVILY_TOOL_ID = "web_search_with_tavily"


def enrich_with_tavily(
    prompt: str, tool_ids: tuple[str, ...], tavily: TavilySearch | None
) -> tuple[str, tuple[str, ...]]:
    if TAVILY_TOOL_ID not in tool_ids:
        return prompt, tool_ids
    if tavily is None:
        raise ValueError("TAVILY_API_KEY is required for Web Search with Tavily")
    results = tavily.search(prompt)
    sources = "\n\n".join(
        f"[{index}] {title}\nURL: {url}\n내용: {content}"
        for index, (title, url, content) in enumerate(results, start=1)
    )
    enriched = (
        f"{prompt}\n\n아래는 Tavily가 수집한 최신 검색 결과입니다. "
        "이 자료만 근거로 답변하고, 출처 URL을 각 항목에 포함하세요.\n\n"
        f"--- 검색 결과 ---\n{sources}"
    )
    return enriched, tuple(tool_id for tool_id in tool_ids if tool_id != TAVILY_TOOL_ID)
