"""
主线链动策略盘后观察入口
"""

from __future__ import annotations

import argparse
from datetime import date
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.mainline_rebalance_executor import execute_due_rebalance
from backtest.mainline_observer import observe_account, push_observation
from backtest.paper_trading import DEFAULT_PAPER_TRADING_PATH


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="主线链动策略盘后观察")
    parser.add_argument("--account-id", type=int, default=1, help="模拟盘账户 ID，默认 1")
    parser.add_argument("--db-path", default=str(DEFAULT_PAPER_TRADING_PATH), help="模拟盘数据库路径")
    parser.add_argument("--cache-path", default="data/market_cache.sqlite3", help="本地行情缓存路径")
    parser.add_argument("--as-of-date", default=None, help="观察日期，格式 YYYY-MM-DD，默认当天")
    parser.add_argument("--bark-url", default="", help="Bark 推送地址")
    parser.add_argument("--push", action="store_true", help="是否发送 Bark 推送")
    args = parser.parse_args()

    requested_date = date.fromisoformat(args.as_of_date) if args.as_of_date else date.today()
    execution_result = execute_due_rebalance(
        account_id=args.account_id,
        trade_date=requested_date,
        db_path=Path(args.db_path),
        cache_path=Path(args.cache_path),
    )
    if execution_result.executed:
        print(
            "已补执行明日预案: "
            f"{execution_result.signal_date.isoformat()} -> {execution_result.trade_date.isoformat()} "
            f"创建 {execution_result.created_orders} 笔, "
            f"成交 {execution_result.filled_orders} 笔, "
            f"部分成交 {execution_result.partial_filled_orders} 笔, "
            f"拒单 {execution_result.rejected_orders} 笔"
        )

    result = observe_account(
        account_id=args.account_id,
        requested_date=requested_date,
        db_path=Path(args.db_path),
        cache_path=Path(args.cache_path),
    )
    print(result.summary_text)

    if args.push:
        if not args.bark_url:
            raise SystemExit("--push 时必须传入 --bark-url")
        try:
            push_observation(result, args.bark_url)
            print("Bark 推送已发送")
        except Exception as exc:
            print(f"Bark 推送失败: {exc}")


if __name__ == "__main__":
    main()
