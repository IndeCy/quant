#!/usr/bin/env python3
"""把组合重平衡提醒写入现有 APScheduler job store，不触发任务。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apscheduler.schedulers.base import STATE_STOPPED

from runtime.paths import get_runtime_paths
from runtime.portfolio_rebalance_scheduler import install_portfolio_rebalance_job
from runtime.scheduler import create_scheduler


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    paths = get_runtime_paths()
    scheduler = create_scheduler(paths)
    scheduler.start(paused=True)
    try:
        job = install_portfolio_rebalance_job(scheduler, paths, push=args.push)
        result = {
            "job_id": job.id,
            "schedule": str(job.trigger),
            "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
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
