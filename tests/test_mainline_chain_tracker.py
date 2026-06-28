"""
测试主线链动策略模拟盘跟踪脚本
"""

from pathlib import Path

from backtest.paper_trading import PaperTradingStore
from examples.track_mainline_chain_momentum import (
    build_bark_url,
    build_status_text,
    format_order_line,
    initialize_default_pending_orders,
)


def test_initialize_default_pending_orders(tmp_path: Path):
    """初始化脚本应写入用户提交的四笔待成交委托。"""
    db_path = tmp_path / "paper.sqlite3"

    account_id = initialize_default_pending_orders(db_path=db_path)

    store = PaperTradingStore(db_path)
    try:
        account = store.get_account(account_id)
        orders = store.list_orders(account_id, status="PENDING")
        assert account["strategy_code"] == "Mainline_Chain_Momentum"
        assert len(orders) == 4
        assert sum(order["amount"] for order in orders) == 997180.0
        assert {order["symbol"] for order in orders} == {
            "601138.SH",
            "000063.SZ",
            "300308.SZ",
            "300502.SZ",
        }
    finally:
        store.close()


def test_format_order_line_uses_fill_price_for_filled_order():
    """成交委托展示时应优先显示成交价，避免和成交金额不一致。"""
    line = format_order_line(
        {
            "status": "FILLED",
            "side": "BUY",
            "symbol": "300502.SZ",
            "symbol_name": "新易盛",
            "price": 775.94,
            "fill_price": 790.13,
            "quantity": 300,
            "amount": 237039.0,
        }
    )

    assert "790.130" in line
    assert "237039.00" in line


def test_build_bark_url_quotes_chinese_content():
    """Bark URL 应对中文标题和内容做 URL 编码。"""
    url = build_bark_url("https://api.day.app/key", "主线链动策略", "今日无需调仓")

    assert url == "https://api.day.app/key/%E4%B8%BB%E7%BA%BF%E9%93%BE%E5%8A%A8%E7%AD%96%E7%95%A5/%E4%BB%8A%E6%97%A5%E6%97%A0%E9%9C%80%E8%B0%83%E4%BB%93"


def test_build_status_text_contains_pending_and_positions(tmp_path: Path):
    """状态文本应包含账户、委托和持仓，便于推送到手机。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = initialize_default_pending_orders(db_path=db_path)

    text = build_status_text(account_id, db_path=db_path)

    assert "主线链动策略" in text
    assert "PENDING BUY" in text


def test_build_status_text_contains_macro_risk_warning(tmp_path: Path):
    """处于重大宏观事件窗口时，状态文本应带风险提示。"""
    db_path = tmp_path / "paper.sqlite3"
    account_id = initialize_default_pending_orders(db_path=db_path)

    text = build_status_text(account_id, db_path=db_path, as_of_date="2026-06-09")

    assert "宏观风险提示" in text
    assert "美国5月CPI" in text
