#!/usr/bin/env python3
"""创建发布基线和运行数据备份包。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.paths import RuntimePaths
from runtime.release_baseline import create_release_baseline


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-root", default="", help="运行目录根路径，默认使用 QUANT_HOME 或项目 runtime")
    parser.add_argument("--output-dir", default="", help="备份输出目录")
    parser.add_argument("--label", default="release", help="发布基线标签")
    args = parser.parse_args()
    paths = RuntimePaths(Path(args.runtime_root)) if args.runtime_root else None
    result = create_release_baseline(
        paths=paths,
        output_dir=Path(args.output_dir) if args.output_dir else None,
        label=args.label,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
