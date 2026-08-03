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
