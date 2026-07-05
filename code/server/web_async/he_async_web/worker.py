"""RQ worker entrypoint for async HE jobs."""

from __future__ import annotations

import argparse

from redis import Redis
from rq import Queue, Worker

from .runner import run_cpp_job
from .settings import get_settings
from .storage import init_db


def run_he_job(job_id: str) -> dict[str, object]:
    settings = get_settings()
    init_db(settings)
    return run_cpp_job(job_id, settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an RQ worker for HE jobs.")
    parser.add_argument("--redis-url", default=None)
    parser.add_argument("--queue", default=None)
    parser.add_argument("--burst", action="store_true", help="Exit when all queued jobs are done.")
    args = parser.parse_args()

    settings = get_settings()
    redis_url = args.redis_url or settings.redis_url
    queue_name = args.queue or settings.queue_name
    init_db(settings)

    connection = Redis.from_url(redis_url)
    queue = Queue(queue_name, connection=connection)
    worker = Worker([queue], connection=connection)
    worker.work(burst=args.burst)


if __name__ == "__main__":
    main()
