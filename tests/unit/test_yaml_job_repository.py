from textwrap import dedent

from prompt_dispatcher.adapters.outbound.repositories.yaml_job import YamlJobRepository


def test_invalid_cron_does_not_load_job_or_block_repository(tmp_path) -> None:
    (tmp_path / "invalid.job.yaml").write_text(
        """
version: 1
id: invalid
schedule:
  cron: "0 24-0 * * *"
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: hello
delivery:
  channels:
    - type: fake
      target: one
""".strip(),
        encoding="utf-8",
    )

    repository = YamlJobRepository(tmp_path)

    assert repository.find_all() == []
    assert repository.errors
    assert "invalid.job.yaml: invalid cron expression" in repository.errors[0]


def test_research_task_id_allows_hyphens(tmp_path) -> None:
    (tmp_path / "news.job.yaml").write_text(
        """
version: 1
id: news
schedule:
  cron: "0 7 * * *"
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: hello
delivery:
  channels:
    - type: fake
      target: one
research:
  tasks:
    - id: mobility-ai
      name: Mobility AI
      query: latest mobility news
""".strip(),
        encoding="utf-8",
    )

    repository = YamlJobRepository(tmp_path)

    assert repository.errors == []
    assert repository.find_all()[0].research_tasks[0].id == "mobility-ai"


def test_research_task_loads_kbo_source_without_web_search(tmp_path) -> None:
    (tmp_path / "kbo.job.yaml").write_text(
        """\
version: 1
id: kbo
schedule:
  cron: "0 7 * * *"
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: hello
delivery:
  channels:
    - type: fake
      target: one
research:
  tasks:
    - id: samsung
      name: 삼성 경기 결과
      use_web_search: false
      kbo_sources:
        - id: samsung_results
          name: 삼성 최근 경기
          data_type: latest_results
          team: SS
          limit: 3
""".strip(),
        encoding="utf-8",
    )

    repository = YamlJobRepository(tmp_path)

    assert repository.errors == []
    source = repository.find_all()[0].research_tasks[0].kbo_sources[0]
    assert source.team == "SS"
    assert source.limit == 3


def test_research_task_weekdays_are_loaded(tmp_path) -> None:
    (tmp_path / "weekdays.job.yaml").write_text(
        """\
version: 1
id: weekdays
schedule:
  cron: "0 7 * * 0,2,4"
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: hello
delivery:
  channels:
    - type: fake
      target: one
research:
  tasks:
    - id: economy
      query: latest economy news
      days_of_week: [mon, fri]
      include_raw_content: true
""",
        encoding="utf-8",
    )

    repository = YamlJobRepository(tmp_path)

    assert repository.errors == []
    assert repository.find_all()[0].research_tasks[0].days_of_week == ("mon", "fri")
    assert repository.find_all()[0].research_tasks[0].include_raw_content is True


def test_weather_only_research_task_is_loaded(tmp_path) -> None:
    content = dedent(
        """\
        version: 1
        id: weather
        schedule:
          cron: "0 7 * * *"
          timezone: Asia/Seoul
        openwebui:
          model: test-model
        prompt:
          text: hello
        delivery:
          channels:
            - type: fake
              target: one
        research:
          tasks:
            - id: today_weather
              name: 오늘 날씨
              use_web_search: false
              use_prompt: false
              weather_sources:
                - id: seoul
                  name: 서울
                  latitude: 37.5665
                  longitude: 126.9780
                  include_alerts: true
                  include_weekly: true
        """
    )
    (tmp_path / "weather.job.yaml").write_text(content, encoding="utf-8")

    repository = YamlJobRepository(tmp_path)

    assert repository.errors == []
    task = repository.find_all()[0].research_tasks[0]
    assert task.use_web_search is False
    assert task.use_prompt is False
    assert task.weather_sources[0].id == "seoul"
    assert task.weather_sources[0].include_alerts is True
    assert task.weather_sources[0].include_weekly is True


def test_air_quality_only_research_task_is_loaded(tmp_path) -> None:
    content = """
version: 1
id: air
name: 대기질
enabled: true
schedule:
  cron: 0 9 * * *
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: '{{ research_context }}'
delivery:
  channels:
    - type: fake
      target: test
research:
  tasks:
    - id: air
      name: 서울 대기질
      query: ''
      use_web_search: false
      air_quality_sources:
        - id: seoul-air
          name: 서울 대기질
          address: 서울
          latitude: 37.5665
          longitude: 126.978
"""
    (tmp_path / "air.job.yaml").write_text(content, encoding="utf-8")
    repository = YamlJobRepository(tmp_path)

    assert not repository.errors
    source = repository.find_by_id("air").research_tasks[0].air_quality_sources[0]
    assert source.address == "서울"


def test_job_collector_only_research_task_is_loaded(tmp_path) -> None:
    (tmp_path / "jobs.job.yaml").write_text(
        '''\
version: 1
id: jobs
schedule:
  cron: "0 18 * * mon"
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: hello
delivery:
  channels:
    - type: fake
      target: one
research:
  tasks:
    - id: education_jobs
      name: 교육 콘텐츠 채용
      use_web_search: false
      use_prompt: false
      job_collector_sources:
        - id: education_postings
          name: 교육 콘텐츠 공고
          profile_id: education
          keyword: 콘텐츠 개발
          statuses: [ACTIVE]
          limit: 10
''',
        encoding="utf-8",
    )

    repository = YamlJobRepository(tmp_path)

    assert repository.errors == []
    task = repository.find_all()[0].research_tasks[0]
    assert task.use_web_search is False
    assert task.job_collector_sources[0].profile_id == "education"
    assert task.job_collector_sources[0].keyword == "콘텐츠 개발"


def test_duplicate_research_task_ids_do_not_load_job(tmp_path) -> None:
    (tmp_path / "duplicate.job.yaml").write_text(
        """\
version: 1
id: duplicate
schedule:
  cron: "0 7 * * *"
  timezone: Asia/Seoul
openwebui:
  model: test-model
prompt:
  text: hello
delivery:
  channels:
    - type: fake
      target: one
research:
  tasks:
    - id: politics
      query: first
    - id: politics
      query: second
""",
        encoding="utf-8",
    )

    repository = YamlJobRepository(tmp_path)

    assert repository.find_all() == []
    assert "research task ids must be unique: politics" in repository.errors[0]
