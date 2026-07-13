#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.operations_observation import (  # noqa: E402
    build_operations_observation,
    write_operations_observation,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="生成长期运行观察摘要")
    parser.add_argument("--repo-root", default=".", help="仓库根目录")
    parser.add_argument("--output-dir", default="docs/release", help="报告输出目录")
    args = parser.parse_args()

    report = build_operations_observation(Path(args.repo_root))
    paths = write_operations_observation(report, Path(args.output_dir))
    print(f"Markdown: {paths['markdown']}")
    print(f"JSON: {paths['json']}")
    print(f"Ready: {report['ready_for_daily_review']}")


if __name__ == "__main__":
    main()
