#!/usr/bin/env python3
"""运行主线链动每日观察并同步监控指标。"""

from __future__ import annotations

import argparse
from datetime import date
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backtest.mainline_observer import observe_account, push_observation
from backtest.mainline_rebalance_executor import execute_due_rebalance
from monitoring.mainline_adapter import sync_mainline_chain_monitoring
from runtime.paths import get_runtime_paths


def main() -> None:
    """盘后执行主线链动影子实盘观察，并把结果写入统一监控库。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account-id", type=int, default=1)
    parser.add_argument("--as-of-date", default=None)
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--bark-url", default=os.getenv("BARK_URL", ""))
    args = parser.parse_args()

    paths = get_runtime_paths()
    paths.ensure_directories()
    requested_date = date.fromisoformat(args.as_of_date) if args.as_of_date else date.today()
    cache_path = paths.data_dir / "market_cache.sqlite3"

    execution_result = execute_due_rebalance(
        account_id=args.account_id,
        trade_date=requested_date,
        db_path=paths.paper_trading_path,
        cache_path=cache_path,
    )
    if execution_result.executed:
        print(
            "已补执行明日预案: "
            f"{execution_result.signal_date.isoformat()} -> "
            f"{execution_result.trade_date.isoformat()} "
            f"创建 {execution_result.created_orders} 笔, "
            f"成交 {execution_result.filled_orders} 笔, "
            f"拒单 {execution_result.rejected_orders} 笔"
        )

    result = observe_account(
        account_id=args.account_id,
        requested_date=requested_date,
        db_path=paths.paper_trading_path,
        cache_path=cache_path,
    )
    print(result.summary_text)
    summary = sync_mainline_chain_monitoring(paths)
    print(f"监控同步完成: {summary}")

    if args.push:
        if not args.bark_url:
            raise SystemExit("--push 需要传入 --bark-url 或设置 BARK_URL")
        push_observation(result, args.bark_url)
        print("Bark 推送已发送")


if __name__ == "__main__":
    main()
