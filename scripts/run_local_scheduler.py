#!/usr/bin/env python3
"""启动本地每日调度器。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.paths import get_runtime_paths
from runtime.scheduler import create_scheduler, install_daily_pipeline_jobs, write_scheduler_heartbeat


def main() -> None:
    """启动常驻调度进程，适合后续迁移到 Mac mini 后托管。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hour", type=int, default=16)
    parser.add_argument("--minute", type=int, default=30)
    parser.add_argument("--skip-update", action="store_true")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    paths = get_runtime_paths()
    scheduler = create_scheduler(paths)
    jobs = install_daily_pipeline_jobs(
        scheduler,
        paths,
        hour=args.hour,
        minute=args.minute,
        skip_update=args.skip_update,
        push=args.push,
    )
    scheduler.start()
    write_scheduler_heartbeat(paths)
    job_ids = ", ".join(job.id for job in jobs)
    print(f"local scheduler started: {job_ids} at {args.hour:02d}:{args.minute:02d}")
    try:
        while True:
            time.sleep(60)
            write_scheduler_heartbeat(paths)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
