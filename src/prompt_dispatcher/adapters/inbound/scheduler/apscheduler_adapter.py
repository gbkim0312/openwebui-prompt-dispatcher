from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from prompt_dispatcher.domain.job import Job


class ApschedulerAdapter:
    def __init__(self) -> None:
        self._scheduler = BackgroundScheduler(timezone="UTC")

    @property
    def running(self) -> bool:
        return bool(self._scheduler.running)

    def register(self, job: Job, callback: Callable[[str], None]) -> None:
        self._scheduler.add_job(
            lambda: callback(job.id),
            CronTrigger.from_crontab(job.schedule.cron, timezone=job.schedule.timezone),
            id=job.id,
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
