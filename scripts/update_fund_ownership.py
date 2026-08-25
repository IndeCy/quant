"""更新 Tushare 公募基金披露持仓研究缓存。"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tushare as ts

from data.fund_ownership_cache import update_fund_ownership_cache
from runtime.config import get_config_value
from runtime.paths import get_runtime_paths


def main() -> None:
    """读取统一配置，按季度执行可恢复的分页同步。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-period", default="20131231")
    parser.add_argument("--end-period", required=True)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    paths = get_runtime_paths()
    paths.ensure_directories()
    result = update_fund_ownership_cache(
        ts.pro_api(token),
        paths.fund_ownership_path,
        start_period=args.start_period,
        end_period=args.end_period,
        force=args.force,
    )
    print(result)


if __name__ == "__main__":
    main()
