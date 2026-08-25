#!/usr/bin/env python3
"""运行一次组合建仓/重平衡检查，只提醒、不交易。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.paths import get_runtime_paths
from runtime.portfolio_rebalance_monitor import (
    load_rebalance_config,
    record_failure_and_maybe_notify,
    run_monitor,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/portfolio_rebalance.json")
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    config = load_rebalance_config(config_path)
    paths = get_runtime_paths()
    try:
        result = run_monitor(config, paths, push=args.push, dry_run=args.dry_run)
    except Exception as error:
        notification_status = "SKIPPED"
        if not args.dry_run:
            notification = record_failure_and_maybe_notify(
                config,
                paths,
                error,
                push=args.push,
            )
            notification_status = notification.status
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error": str(error),
                    "notification_status": notification_status,
                    "automatic_trade": False,
                },
                ensure_ascii=False,
            )
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
