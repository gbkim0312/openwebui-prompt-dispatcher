from pathlib import Path

import pytest

from prompt_dispatcher.adapters.outbound.repositories.web_management import WebManagementStore
from prompt_dispatcher.domain.errors import JobValidationError


def _document(*, team: str | None) -> dict[str, object]:
    return {
        "version": 1,
        "schedule": {"cron": "0 23 * * tue,wed,thu,fri,sat,sun", "timezone": "Asia/Seoul"},
        "openwebui": {"model": "test-model"},
        "delivery": {"channels": [{"type": "fake", "target": "personal"}]},
        "research": {
            "tasks": [
                {
                    "id": "lineup",
                    "use_web_search": False,
                    "kbo_sources": [
                        {"id": "lineup_data", "data_type": "lineups", "team": team}
                    ],
                }
            ]
        },
    }


def test_invalid_web_job_edit_does_not_replace_existing_job(tmp_path: Path) -> None:
    store = WebManagementStore(tmp_path / "jobs", tmp_path / "prompts", tmp_path / "data.env")
    store.save_job("kbo", _document(team="SS"), "existing prompt")

    with pytest.raises(JobValidationError, match="game_id or team"):
        store.save_job("kbo", _document(team=None), "invalid replacement")

    assert "team: SS" in (tmp_path / "jobs" / "kbo.job.yaml").read_text(encoding="utf-8")
    assert store.read_prompt("kbo") == "existing prompt"
