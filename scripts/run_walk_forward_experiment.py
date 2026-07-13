#!/usr/bin/env python3
"""运行 Walk-Forward 实验登记。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.walk_forward import WalkForwardWindow, run_walk_forward_experiment


def main() -> None:
    """命令行入口，用于把参数指标表登记成 Walk-Forward 实验。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-csv", required=True, help="包含 window/sample/parameter_id/指标列的 CSV")
    parser.add_argument("--windows-json", required=True, help="Walk-Forward 窗口 JSON 数组")
    parser.add_argument("--experiment-id", default="quality_walk_forward_research")
    parser.add_argument("--name", default="Quality Walk Forward Research")
    parser.add_argument("--run-date", default="")
    parser.add_argument("--message", default="")
    args = parser.parse_args()

    metric_frame = pd.read_csv(args.input_csv)
    windows = [WalkForwardWindow(**item) for item in json.loads(args.windows_json)]
    result = run_walk_forward_experiment(
        metric_frame=metric_frame,
        windows=windows,
        experiment_id=args.experiment_id,
        name=args.name,
        run_date=args.run_date or None,
        message=args.message,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
