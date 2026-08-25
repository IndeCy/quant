#!/usr/bin/env python3
"""执行生产数据质量门禁。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.data_quality_gate import run_data_quality_gate


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-trade-date", default="", help="要求关键表至少更新到该日期，格式 YYYYMMDD")
    parser.add_argument("--strict", action="store_true", help="失败时以异常退出")
    args = parser.parse_args()
    result = run_data_quality_gate(min_trade_date=args.min_trade_date, raise_on_fail=args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
