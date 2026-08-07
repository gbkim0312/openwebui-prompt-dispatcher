import httpx

from prompt_dispatcher.adapters.outbound.job_collector.client import JobCollectorClient
from prompt_dispatcher.domain.job import JobCollectorSource


def test_job_collector_fetches_saved_postings_with_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/jobs"
        assert request.url.params["profile_id"] == "education"
        assert request.url.params["keyword"] == "콘텐츠 개발"
        assert request.url.params["statuses"] == "ACTIVE"
        assert request.url.params["employment_types"] == "정규직"
        assert request.headers["authorization"] == "Bearer admin-key"
        return httpx.Response(200, json={"items": [{"title": "교육 콘텐츠 개발자"}]})

    client = JobCollectorClient(
        "http://collector.test",
        "admin-key",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = client.fetch(
        JobCollectorSource(
            "education_jobs",
            "교육 공고",
            profile_id="education",
            keyword="콘텐츠 개발",
            employment_types=("FULL_TIME",),
        )
    )

    assert "교육 공고" in result
    assert "교육 콘텐츠 개발자" in result
