#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.safe_commit_review import (  # noqa: E402
    build_safe_commit_review,
    write_safe_commit_review,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成安全提交审查清单")
    parser.add_argument(
        "--baseline",
        default="docs/release/git_baseline_report.json",
        help="Git baseline JSON 路径",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/release",
        help="审查清单输出目录",
    )
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    review = build_safe_commit_review(baseline)
    paths = write_safe_commit_review(review, Path(args.output_dir))
    print(f"Markdown: {paths['markdown']}")
    print(f"JSON: {paths['json']}")
    print(f"Ready: {review['ready_for_selective_commit']}")


if __name__ == "__main__":
    main()
