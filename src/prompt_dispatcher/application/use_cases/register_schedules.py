import logging

from prompt_dispatcher.application.dto.commands import RunJobCommand
from prompt_dispatcher.application.ports.job_repository import JobRepositoryPort
from prompt_dispatcher.application.ports.scheduler import SchedulerPort
from prompt_dispatcher.application.use_cases.run_job import RunJob

logger = logging.getLogger(__name__)


class RegisterSchedules:
    def __init__(self, jobs: JobRepositoryPort, scheduler: SchedulerPort, run_job: RunJob) -> None:
        self._jobs, self._scheduler, self._run = jobs, scheduler, run_job

    def execute(self) -> int:
        self._scheduler.clear()
        count = 0
        for job in self._jobs.find_all():
            if job.enabled:

                def callback(job_id: str) -> None:
                    self._run.execute(RunJobCommand(job_id))

                try:
                    schedules = (job.schedule, *job.schedules)
                    for schedule in schedules:
                        self._scheduler.register(job, callback, schedule, schedule.id)
                        count += 1
                except Exception as exc:
                    logger.error(
                        "event=schedule_registration_failed job_id=%s error_type=%s error=%s",
                        job.id,
                        type(exc).__name__,
                        exc,
                    )
        return count
