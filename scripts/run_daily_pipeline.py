#!/usr/bin/env python3
"""执行唯一每日交易流水线。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.daily_pipeline import run_production_daily_pipeline


def main() -> None:
    """命令行入口，供调度器、手动补跑和 API 统一复用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="运行完成后发送统一 Bark 汇总通知")
    parser.add_argument("--source", default="manual", choices=["manual", "scheduler", "api"], help="触发来源")
    args = parser.parse_args()
    summary = run_production_daily_pipeline(push=args.push, source=args.source)
    print(summary)


if __name__ == "__main__":
    main()
