#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.git_baseline import build_git_baseline_report, write_git_baseline_report


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 Git 提交基线分类报告")
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Git 仓库根目录，默认当前目录",
    )
    parser.add_argument(
        "--output-dir",
        default="docs/release",
        help="报告输出目录，默认 docs/release",
    )
    parser.add_argument(
        "--no-ignored",
        action="store_true",
        help="不扫描 git ignored 文件",
    )
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    output_dir = Path(args.output_dir)
    report = build_git_baseline_report(
        repo_root=repo_root,
        include_ignored=not args.no_ignored,
    )
    paths = write_git_baseline_report(report, output_dir)
    print(f"Markdown: {paths['markdown']}")
    print(f"JSON: {paths['json']}")


if __name__ == "__main__":
    main()
