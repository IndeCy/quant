#!/usr/bin/env python3
"""回填主线链动 Tushare 历史行情缓存。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.mainline_tushare_backfill import backfill_mainline_tushare_cache


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20210101", help="回填开始日期，YYYYMMDD")
    parser.add_argument("--end-date", default=None, help="回填结束日期，YYYYMMDD，默认今天")
    parser.add_argument("--sleep-seconds", type=float, default=0.25, help="每个标的之间的等待秒数，避免触发频控")
    args = parser.parse_args()
    result = backfill_mainline_tushare_cache(
        start_date=args.start_date,
        end_date=args.end_date,
        sleep_seconds=args.sleep_seconds,
    )
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
