#!/usr/bin/env python3
"""增量更新 Tushare 重要股东增减持缓存。"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import tushare as ts

from data.holder_trades import update_holder_trade_cache
from runtime.config import get_config_value
from runtime.paths import get_runtime_paths


def main() -> None:
    """执行可重复的公告日增量同步。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="20140101")
    parser.add_argument("--end-date", default=pd.Timestamp.today().strftime("%Y%m%d"))
    parser.add_argument("--force-full", action="store_true")
    args = parser.parse_args()
    token = get_config_value("TUSHARE_TOKEN", prefer_environ=True)
    if not token:
        raise RuntimeError("缺少 TUSHARE_TOKEN 配置")
    result = update_holder_trade_cache(
        ts.pro_api(token),
        get_runtime_paths().holder_trade_path,
        start_date=args.start_date,
        end_date=args.end_date,
        force_full=args.force_full,
    )
    print(result)


if __name__ == "__main__":
    main()
