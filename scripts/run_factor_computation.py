#!/usr/bin/env python3
"""从 CSV 运行一次标准因子分数入库。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.factor_computation_runner import run_factor_computation


class CsvFactorCalculator:
    """CSV 因子计算器，用于把外部研究结果标准化入库。"""

    def __init__(self, path: Path) -> None:
        self.path = path

    def compute(self, contract: dict, trade_date: str) -> pd.DataFrame:
        """读取包含 symbol、value，可选 close 的 CSV。"""
        return pd.read_csv(self.path)


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factor-id", required=True)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--input-csv", required=True)
    args = parser.parse_args()
    result = run_factor_computation(
        paths=None,
        factor_id=args.factor_id,
        trade_date=args.trade_date,
        calculator=CsvFactorCalculator(Path(args.input_csv)),
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
