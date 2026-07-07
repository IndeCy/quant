#!/usr/bin/env python3
"""运行调度稳定性巡检。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.scheduler_watchdog import run_scheduler_watchdog


def main() -> None:
    """命令行入口，供 APScheduler 调用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="仅异常时发送 Bark 通知")
    parser.add_argument("--trade-date", default="", help="指定巡检交易日，格式 YYYYMMDD；默认使用当天")
    args = parser.parse_args()
    result = run_scheduler_watchdog(push=args.push, trade_date=args.trade_date or None)
    print(json.dumps(asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
