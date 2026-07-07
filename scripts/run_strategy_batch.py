#!/usr/bin/env python3
"""运行所有已启用策略实例。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.strategy_batch_runner import run_enabled_strategy_instances


def main() -> None:
    """命令行入口，供 APScheduler 调用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="运行策略后发送已配置的 Bark 通知")
    parser.add_argument("--trade-date", default="", help="指定补跑交易日，格式 YYYYMMDD；默认使用当天")
    args = parser.parse_args()
    summary = run_enabled_strategy_instances(push=args.push, trade_date=args.trade_date or None)
    print(summary)


if __name__ == "__main__":
    raise SystemExit("请使用 scripts/run_daily_pipeline.py 执行完整原子流水线")
