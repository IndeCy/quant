#!/usr/bin/env python3
"""刷新本地 Data Catalog。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runtime.data_catalog_runner import refresh_data_catalog


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", action="append", default=[], help="额外扫描目录，可重复传入")
    args = parser.parse_args()
    roots = [Path(item) for item in args.root] if args.root else None
    result = refresh_data_catalog(roots=roots)
    print(json.dumps({key: value for key, value in result.items() if key != "sources"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
