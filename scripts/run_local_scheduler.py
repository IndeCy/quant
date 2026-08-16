#!/usr/bin/env python3
"""启动本地每日调度器。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.paths import get_runtime_paths
from runtime.etf_premium_scheduler import install_etf_premium_monitor_jobs
from runtime.portfolio_rebalance_scheduler import install_portfolio_rebalance_job
from runtime.scheduler import create_scheduler, install_daily_pipeline_jobs
from runtime.scheduler_liveness import wake_scheduler_after_system_resume


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
    scheduler.start(paused=True)
    jobs = install_daily_pipeline_jobs(
        scheduler,
        paths,
        hour=args.hour,
        minute=args.minute,
        skip_update=args.skip_update,
        push=args.push,
    )
    jobs.extend(install_etf_premium_monitor_jobs(scheduler, paths, push=args.push))
    jobs.append(install_portfolio_rebalance_job(scheduler, paths, push=args.push))
    scheduler.resume()
    wake_scheduler_after_system_resume(scheduler, paths)
    job_ids = ", ".join(job.id for job in jobs)
    print(f"local scheduler started: {job_ids} at {args.hour:02d}:{args.minute:02d}")
    try:
        while True:
            time.sleep(60)
            # macOS 从休眠恢复后主动重扫到期任务，不能只证明进程仍存活。
            wake_scheduler_after_system_resume(scheduler, paths)
    except KeyboardInterrupt:
        scheduler.shutdown()


if __name__ == "__main__":
    main()
