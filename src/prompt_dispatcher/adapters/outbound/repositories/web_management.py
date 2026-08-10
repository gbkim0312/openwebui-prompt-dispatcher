import json
import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from prompt_dispatcher.adapters.outbound.repositories.yaml_job import YamlJobRepository
from prompt_dispatcher.domain.errors import JobValidationError


class WebManagementStore:
    """Safe local-filesystem boundary used exclusively by the admin UI."""

    def __init__(self, jobs: Path, prompts: Path, secrets: Path) -> None:
        self._jobs, self._prompts, self._secrets = jobs, prompts, secrets

    @staticmethod
    def _safe_id(value: str) -> str:
        if not value or not value.replace("-", "").replace("_", "").isalnum():
            raise JobValidationError("ID may use letters, numbers, hyphens, and underscores only")
        return value

    @staticmethod
    def _write(path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(content)
        Path(temporary).replace(path)

    def save_job(self, job_id: str, document: Mapping[str, Any], prompt: str) -> None:
        job_id = self._safe_id(job_id)
        payload = dict(document)
        payload["id"] = job_id
        prompt_config = dict(payload.get("prompt", {}))
        prompt_config["file"] = f"{job_id}.md"
        prompt_config.pop("text", None)
        payload["prompt"] = prompt_config
        serialized = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
        self._validate_job_document(serialized)
        self._write(self._prompts / f"{job_id}.md", prompt)
        self._write(self._jobs / f"{job_id}.job.yaml", serialized)

    @staticmethod
    def _validate_job_document(serialized: str) -> None:
        """Validate in isolation so a rejected web edit never replaces the existing job."""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "candidate.job.yaml"
            path.write_text(serialized, encoding="utf-8")
            errors = YamlJobRepository(Path(temporary)).errors
        if errors:
            raise JobValidationError(errors[0].split(": ", 1)[-1])

    def read_prompt(self, job_id: str) -> str:
        path = self._prompts / f"{self._safe_id(job_id)}.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def delete_job(self, job_id: str) -> None:
        job_id = self._safe_id(job_id)
        for path in (self._jobs / f"{job_id}.job.yaml", self._prompts / f"{job_id}.md"):
            if path.exists():
                path.unlink()

    def configured_keys(self) -> set[str]:
        return {key for key, value in self.read_values().items() if value}

    def read_values(self) -> dict[str, str]:
        allowed = {
            "OPENWEBUI_BASE_URL",
            "OPENWEBUI_API_KEY",
            "NEXTCLOUD_URL",
            "TELEGRAM_PERSONAL_BOT_TOKEN",
            "TELEGRAM_PERSONAL_CHAT_ID",
            "NEXTCLOUD_TALK_PERSONAL_USERNAME",
            "NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD",
            "NEXTCLOUD_TALK_PERSONAL_ROOM_TOKEN",
            "NEXTCLOUD_TALK_ROOMS",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_USE_TLS",
            "SMTP_PERSONAL_TO",
            "EXECUTION_RETENTION_DAYS",
            "WEATHER_ENGINE",
            "KMA_SERVICE_KEY",
            "KMA_ALERT_SERVICE_KEY",
            "KMA_MID_SERVICE_KEY",
            "AIRKOREA_SERVICE_KEY",
            "KAKAO_REST_API_KEY",
            "KBO_API_BASE_URL",
            "KBO_ADMIN_API_KEY",
            "JOB_COLLECTOR_BASE_URL",
            "JOB_COLLECTOR_ADMIN_API_KEY",
            "JOB_COLLECTOR_PROFILES_JSON",
        }
        stored: dict[str, str] = {}
        if self._secrets.exists():
            stored = {
                line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in self._secrets.read_text(encoding="utf-8").splitlines()
                if "=" in line
            }
        return {key: stored.get(key) or os.getenv(key) or "" for key in allowed}

    def save_secrets(self, values: Mapping[str, str]) -> None:
        allowed = {
            "OPENWEBUI_BASE_URL",
            "OPENWEBUI_API_KEY",
            "NEXTCLOUD_URL",
            "TELEGRAM_PERSONAL_BOT_TOKEN",
            "TELEGRAM_PERSONAL_CHAT_ID",
            "NEXTCLOUD_TALK_PERSONAL_USERNAME",
            "NEXTCLOUD_TALK_PERSONAL_APP_PASSWORD",
            "NEXTCLOUD_TALK_PERSONAL_ROOM_TOKEN",
            "NEXTCLOUD_TALK_ROOMS",
            "SMTP_HOST",
            "SMTP_PORT",
            "SMTP_USERNAME",
            "SMTP_PASSWORD",
            "SMTP_FROM",
            "SMTP_USE_TLS",
            "SMTP_PERSONAL_TO",
            "EXECUTION_RETENTION_DAYS",
            "WEATHER_ENGINE",
            "KMA_SERVICE_KEY",
            "KMA_ALERT_SERVICE_KEY",
            "KMA_MID_SERVICE_KEY",
            "AIRKOREA_SERVICE_KEY",
            "KAKAO_REST_API_KEY",
            "KBO_API_BASE_URL",
            "KBO_ADMIN_API_KEY",
            "JOB_COLLECTOR_BASE_URL",
            "JOB_COLLECTOR_ADMIN_API_KEY",
            "JOB_COLLECTOR_PROFILES_JSON",
        }
        old = {}
        if self._secrets.exists():
            old = {
                line.split("=", 1)[0]: line.split("=", 1)[1]
                for line in self._secrets.read_text().splitlines()
                if "=" in line
            }
        old.update({key: value for key, value in values.items() if key in allowed and value})
        self._write(
            self._secrets, "".join(f"{key}={value}\n" for key, value in sorted(old.items()))
        )

    def read_air_quality_stations(self) -> list[dict[str, object]]:
        path = self._secrets.parent / "airkorea_stations.json"
        if not path.exists():
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        return payload if isinstance(payload, list) else []

    def save_air_quality_stations(self, stations: list[dict[str, object]]) -> None:
        path = self._secrets.parent / "airkorea_stations.json"
        self._write(path, json.dumps(stations, ensure_ascii=False, separators=(",", ":")))

    def tail_log(self, limit: int = 200) -> list[str]:
        path = self._secrets.parent / "dispatcher.log"
        if not path.exists():
            return []
        return path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
