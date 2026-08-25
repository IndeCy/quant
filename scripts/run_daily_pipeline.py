#!/usr/bin/env python3
"""执行唯一每日交易流水线。"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.pipeline_service import PipelineService


def main() -> None:
    """命令行入口，供调度器、手动补跑和 API 统一复用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--push", action="store_true", help="运行完成后发送统一 Bark 汇总通知")
    parser.add_argument("--source", default="manual", choices=["manual", "scheduler", "api"], help="触发来源")
    parser.add_argument("--trade-date", default="", help="指定补跑交易日，格式 YYYYMMDD；默认使用当天")
    parser.add_argument("--force", action="store_true", help="明确允许重跑已经成功的交易日")
    args = parser.parse_args()
    trigger_type = {"manual": "MANUAL", "scheduler": "SCHEDULED", "api": "API"}[args.source]
    summary = PipelineService().run(
        pipeline_id="daily_trading_pipeline",
        push=args.push,
        trigger_type=trigger_type,
        trade_date=args.trade_date or None,
        force=args.force,
    )
    print(summary)


if __name__ == "__main__":
    main()
