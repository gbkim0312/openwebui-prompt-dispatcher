from collections.abc import Callable
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from prompt_dispatcher.domain.job import Job, Schedule


class ApschedulerAdapter:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone="UTC")

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    def register(
        self,
        job: Job,
        callback: Callable[[str], None],
        schedule: Schedule | None = None,
        schedule_id: str | None = None,
    ) -> None:
        selected = schedule or job.schedule
        run_date = (
            datetime.fromisoformat(selected.run_at.replace("Z", "+00:00"))
            if selected.run_at
            else None
        )
        trigger = (
            DateTrigger(run_date=run_date, timezone=selected.timezone)
            if selected.run_at
            else CronTrigger.from_crontab(selected.cron, timezone=selected.timezone)
        )
        self._scheduler.add_job(
            lambda: callback(job.id),
            trigger,
            id=f"{job.id}:{schedule_id or selected.id}",
            replace_existing=True,
            max_instances=job.execution_policy.max_instances,
            misfire_grace_time=job.execution_policy.misfire_grace_seconds,
        )

    def start(self) -> None:
        self._scheduler.start()

    def clear(self) -> None:
        self._scheduler.remove_all_jobs()

    def shutdown(self) -> None:
        if self.running:
            self._scheduler.shutdown(wait=False)
