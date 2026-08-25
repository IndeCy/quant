"""更新 Tushare 股东户数本地增量缓存。"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts

from data.shareholder_count import update_shareholder_count_cache
from runtime.config import get_config_value
from runtime.paths import get_runtime_paths


def main() -> None:
    """读取统一配置并执行可恢复的月份分页同步。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20140101")
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--force-full", action="store_true")
    args = parser.parse_args()
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    paths = get_runtime_paths()
    paths.ensure_directories()
    result = update_shareholder_count_cache(
        ts.pro_api(token),
        paths.shareholder_count_path,
        start_date=args.start_date,
        end_date=args.end_date,
        force_full=args.force_full,
    )
    print(result)


if __name__ == "__main__":
    main()
