from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class RunJobCommand:
    job_id: str
    scheduled_time: datetime | None = None
    dry_run: bool = False
    skip_openwebui: bool = False
    fake_channel: bool = False
