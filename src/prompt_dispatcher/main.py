import argparse
import logging
import sys

from prompt_dispatcher.adapters.inbound.http.app import create_app
from prompt_dispatcher.application.dto.commands import RunJobCommand
from prompt_dispatcher.bootstrap.container import build_container
from prompt_dispatcher.bootstrap.logging import configure_logging


def main() -> None:
    parser = argparse.ArgumentParser(prog="prompt-dispatcher")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list")
    sub.add_parser("validate")
    run = sub.add_parser("run")
    run.add_argument("job_id")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--skip-openwebui", action="store_true")
    run.add_argument("--fake-channel", action="store_true")
    sub.add_parser("serve")
    args = parser.parse_args()
    container = build_container()
    configure_logging(container.settings)
    logging.getLogger(__name__).info("event=service_started command=%s", args.command)
    for error in container.jobs.errors:
        logging.getLogger(__name__).error("event=job_configuration_error error=%s", error)
    if args.command == "validate":
        for error in container.jobs.errors:
            print(error, file=sys.stderr)
        available = container.run_job._channels.channel_types
        for job in container.list_jobs.execute():
            if not job.enabled:
                continue
            for destination in job.destinations:
                if destination.channel_type not in available:
                    print(
                        f"{job.id}: unsupported/inactive channel {destination.channel_type}",
                        file=sys.stderr,
                    )
                    container.jobs.errors.append("channel")
        if container.jobs.errors:
            raise SystemExit(1)
        print(f"Valid: {len(container.list_jobs.execute())} job(s)")
        return
    if args.command == "list":
        for job in container.list_jobs.execute():
            print(
                f"{job.id}\t{'enabled' if job.enabled else 'disabled'}\t{job.schedule.cron}\t{job.name}"
            )
        return
    if args.command == "run":
        result = container.run_job.execute(
            RunJobCommand(
                args.job_id,
                dry_run=args.dry_run,
                skip_openwebui=args.skip_openwebui,
                fake_channel=args.fake_channel,
            )
        )
        print(f"{result.status}: {result.execution_id or ''} {result.message or ''}")
        return
    container.register_schedules.execute()
    container.scheduler.start()
    import uvicorn

    try:
        uvicorn.run(
            create_app(container),
            host=container.settings.http_host,
            port=container.settings.http_port,
        )
    finally:
        container.scheduler.shutdown()
