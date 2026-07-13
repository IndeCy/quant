#!/usr/bin/env python3
"""运行开盘后本地 Paper Broker 模拟撮合。"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.market_open_paper_execution import run_market_open_paper_execution


def main() -> None:
    """命令行入口，供 APScheduler 和手动补跑调用。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trade-date", default="")
    parser.add_argument("--push", action="store_true")
    args = parser.parse_args()
    result = run_market_open_paper_execution(
        trade_date=args.trade_date or None,
        push=args.push,
    )
    print(json.dumps(asdict(result), ensure_ascii=False))


if __name__ == "__main__":
    main()
