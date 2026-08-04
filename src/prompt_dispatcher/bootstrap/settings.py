import os
from dataclasses import dataclass
from pathlib import Path


def _truth(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


def _managed_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {
        line.split("=", 1)[0]: line.split("=", 1)[1]
        for line in path.read_text(encoding="utf-8").splitlines()
        if "=" in line and not line.startswith("#")
    }


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Load local development settings without replacing explicit process environment."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _runtime_path(value: str, local_default: str) -> Path:
    """Use project paths when a Docker-only /app mount is unavailable locally."""
    path = Path(value)
    if str(path).startswith("/app/") and not Path("/app").exists():
        return Path(local_default)
    return path


@dataclass(frozen=True)
class Settings:
    log_level: str
    jobs_directory: Path
    prompts_directory: Path
    database_path: Path
    openwebui_base_url: str
    openwebui_api_key: str
    openwebui_verify_tls: bool
    http_host: str
    http_port: int
    enable_fake_channel: bool
    nextcloud_url: str
    nextcloud_verify_tls: bool
    tavily_api_key: str
    execution_retention_days: int
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    smtp_from_address: str
    smtp_use_tls: bool
    weather_engine: str
    kma_service_key: str
    kma_alert_service_key: str
    kma_mid_service_key: str

    @classmethod
    def from_environment(cls) -> "Settings":
        _load_dotenv()
        database = _runtime_path(
            os.getenv("DATABASE_PATH", "data/dispatcher.db"), "data/dispatcher.db"
        )
        managed = _managed_values(database.parent / "management.env")

        def value(key: str, default: str = "") -> str:
            return managed.get(key) or os.getenv(key) or default

        def managed_value(key: str, default: str = "") -> str:
            return managed.get(key) or os.getenv(key) or default

        weather_engine = managed_value("WEATHER_ENGINE", "open_meteo").strip().lower()
        if weather_engine not in {"open_meteo", "kma"}:
            weather_engine = "open_meteo"

        return cls(
            value("LOG_LEVEL", "INFO"),
            _runtime_path(os.getenv("JOBS_DIRECTORY", "jobs"), "jobs"),
            _runtime_path(os.getenv("PROMPTS_DIRECTORY", "prompts"), "prompts"),
            database,
            value("OPENWEBUI_BASE_URL", "http://localhost:8080"),
            value("OPENWEBUI_API_KEY"),
            _truth(os.getenv("OPENWEBUI_VERIFY_TLS", "true")),
            os.getenv("HTTP_HOST", "0.0.0.0"),
            int(os.getenv("HTTP_PORT", "8787")),
            _truth(os.getenv("ENABLE_FAKE_CHANNEL", "false")),
            value("NEXTCLOUD_URL"),
            _truth(os.getenv("NEXTCLOUD_VERIFY_TLS", "true")),
            value("TAVILY_API_KEY"),
            max(1, int(value("EXECUTION_RETENTION_DAYS", "30"))),
            value("SMTP_HOST", "smtp.gmail.com"),
            int(value("SMTP_PORT", "587")),
            value("SMTP_USERNAME"),
            value("SMTP_PASSWORD"),
            value("SMTP_FROM") or value("SMTP_USERNAME"),
            _truth(value("SMTP_USE_TLS", "true")),
            weather_engine,
            managed_value("KMA_SERVICE_KEY"),
            managed_value("KMA_ALERT_SERVICE_KEY"),
            managed_value("KMA_MID_SERVICE_KEY"),
        )
