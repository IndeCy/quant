#!/usr/bin/env python3
"""运行一次 ETF 价格与折溢价监控，只提醒、不交易。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.etf_premium_monitor import (
    load_monitor_config,
    record_failure_and_maybe_notify,
    run_monitor,
)
from runtime.paths import get_runtime_paths


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="config/etf_monitors/513500.json",
        help="相对项目根目录或绝对路径的监控配置",
    )
    parser.add_argument("--push", action="store_true", help="动作信号触发 Bark")
    parser.add_argument("--dry-run", action="store_true", help="忽略时段且不写状态、不发 Bark")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = root / config_path
    config = load_monitor_config(config_path)
    paths = get_runtime_paths()
    try:
        result = run_monitor(
            config,
            paths,
            push=args.push,
            dry_run=args.dry_run,
        )
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
