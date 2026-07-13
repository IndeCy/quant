#!/usr/bin/env python3
"""登记一次最小实验运行。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.experiment_runner import run_manual_experiment


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--name", default="")
    parser.add_argument("--category", default="manual")
    parser.add_argument("--run-date", default="")
    parser.add_argument("--config-json", default="{}")
    parser.add_argument("--metrics-json", default="{}")
    parser.add_argument("--message", default="")
    args = parser.parse_args()
    result = run_manual_experiment(
        experiment_id=args.experiment_id,
        name=args.name,
        category=args.category,
        run_date=args.run_date or None,
        config=json.loads(args.config_json),
        metrics=json.loads(args.metrics_json),
        message=args.message,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
