"""
主线链动策略模拟盘跟踪入口

当前第一版聚焦两件事：
- 记录收盘后提交、尚未成交的模拟委托单
- 查询模拟账户、待成交委托和已成交持仓状态
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backtest.macro_risk import build_default_macro_calendar, format_macro_risk_warning
from backtest.notifier import NotificationMessage, build_notifier
from backtest.paper_trading import DEFAULT_PAPER_TRADING_PATH, PaperTradingStore


STRATEGY_NAME = "主线链动策略"
STRATEGY_CODE = "Mainline_Chain_Momentum"
BENCHMARK_SYMBOL = "000001.SH"
BENCHMARK_NAME = "上证指数"
START_DATE = "2026-06-05"
ORDER_DATE = "2026-06-04"
INITIAL_CASH = 1_000_000.0

DEFAULT_PENDING_ORDERS = [
    ("601138.SH", "工业富联", 78.56, 3300),
    ("000063.SZ", "中兴通讯", 37.75, 6600),
    ("300308.SZ", "中际旭创", 1280.00, 200),
    ("300502.SZ", "新易盛", 775.94, 300),
]


def initialize_default_pending_orders(db_path: Path | str = DEFAULT_PAPER_TRADING_PATH) -> int:
    """按用户 2026-06-04 收盘后提交的模拟单初始化账户。"""
    store = PaperTradingStore(db_path)
    try:
        account_id = store.create_account(
            strategy_name=STRATEGY_NAME,
            strategy_code=STRATEGY_CODE,
            initial_cash=INITIAL_CASH,
            benchmark_symbol=BENCHMARK_SYMBOL,
            benchmark_name=BENCHMARK_NAME,
            start_date=START_DATE,
        )
        for symbol, name, price, quantity in DEFAULT_PENDING_ORDERS:
            store.record_pending_order(
                account_id=account_id,
                order_date=ORDER_DATE,
                symbol=symbol,
                symbol_name=name,
                side="BUY",
                price=price,
                quantity=quantity,
                note="2026-06-04 收盘后提交，等待 2026-06-05 成交确认",
            )
        return account_id
    finally:
        store.close()


def format_order_line(order: dict) -> str:
    """格式化委托行，已成交时优先展示成交价。"""
    display_price = order["fill_price"] if order["status"] == "FILLED" else order["price"]
    return (
        f"- {order['status']} {order['side']} {order['symbol']} "
        f"{order['symbol_name']} {display_price:.3f} * {order['quantity']} "
        f"= {order['amount']:.2f}"
    )


def _parse_date(value: date | str | None) -> date:
    """解析日期参数，默认使用当天。"""
    if value is None:
        return date.today()
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def build_status_text(
    account_id: int,
    db_path: Path | str = DEFAULT_PAPER_TRADING_PATH,
    as_of_date: date | str | None = None,
) -> str:
    """构造适合命令行和手机推送的账户状态文本。"""
    store = PaperTradingStore(db_path)
    try:
        account = store.get_account(account_id)
        orders = store.list_orders(account_id)
        positions = store.list_positions(account_id)
        lines = [
            f"账户: {account['strategy_name']}({account['strategy_code']})",
            f"初始资金: {account['initial_cash']:.2f} 当前现金: {account['cash']:.2f}",
            "委托:",
        ]
        lines.extend(format_order_line(order) for order in orders)
        lines.append("持仓:")
        if not positions:
            lines.append("- 暂无已成交持仓")
        for position in positions:
            lines.append(
                f"- {position['symbol']} {position['symbol_name']} "
                f"{position['quantity']} 股 成本 {position['cost_amount']:.2f}"
            )
        warning = format_macro_risk_warning(
            build_default_macro_calendar(),
            _parse_date(as_of_date),
        )
        if warning:
            lines.extend(["", warning])
        return "\n".join(lines)
    finally:
        store.close()


def build_bark_url(base_url: str, title: str, body: str) -> str:
    """构造 Bark 推送 URL，中文内容必须 URL 编码。"""
    notifier = build_notifier("bark", base_url)
    return notifier.build_url(NotificationMessage(title=title, body=body))


def send_bark_notification(base_url: str, title: str, body: str) -> None:
    """发送 Bark 手机通知。"""
    notifier = build_notifier("bark", base_url)
    notifier.send(NotificationMessage(title=title, body=body))


def print_status(account_id: int, db_path: Path | str = DEFAULT_PAPER_TRADING_PATH) -> None:
    """打印模拟账户状态、待成交委托和当前持仓。"""
    print(build_status_text(account_id, db_path))


def main() -> None:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="主线链动策略模拟盘跟踪")
    parser.add_argument("command", choices=["init", "status", "notify"], help="init 初始化，status 查看状态，notify 推送状态")
    parser.add_argument("--account-id", type=int, help="模拟账户 ID，status 时必填")
    parser.add_argument("--db-path", default=str(DEFAULT_PAPER_TRADING_PATH), help="模拟盘数据库路径")
    parser.add_argument("--bark-url", default=os.getenv("BARK_PUSH_URL", ""), help="Bark 推送基础 URL")
    args = parser.parse_args()

    if args.command == "init":
        account_id = initialize_default_pending_orders(Path(args.db_path))
        print(f"已初始化模拟账户: {account_id}")
        print_status(account_id, Path(args.db_path))
        return

    if args.account_id is None:
        raise SystemExit(f"{args.command} 需要传入 --account-id")
    if args.command == "notify":
        if not args.bark_url:
            raise SystemExit("notify 需要传入 --bark-url 或设置 BARK_PUSH_URL")
        body = build_status_text(args.account_id, Path(args.db_path))
        send_bark_notification(args.bark_url, STRATEGY_NAME, body)
        print("Bark 推送已发送")
        return
    print_status(args.account_id, Path(args.db_path))


if __name__ == "__main__":
    main()
