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
