#!/usr/bin/env python3
"""把 ETF 折溢价监控写入现有 APScheduler job store，不触发任务。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.schedulers.base import STATE_STOPPED

from runtime.etf_premium_scheduler import install_etf_premium_monitor_jobs
from runtime.paths import get_runtime_paths
from runtime.scheduler import create_scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="动作信号触发 Bark")
    args = parser.parse_args()
    paths = get_runtime_paths()
    scheduler = create_scheduler(paths)
    scheduler.start(paused=True)
    try:
        jobs = install_etf_premium_monitor_jobs(scheduler, paths, push=args.push)
        result = {
            "jobs": [
                {
                    "job_id": job.id,
                    "schedule": str(job.trigger),
                    "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                }
                for job in jobs
            ],
            "push": args.push,
            "automatic_trade": False,
        }
    finally:
        if scheduler.state != STATE_STOPPED:
            scheduler.shutdown()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
