"""Paper T+1 执行 SLA 审计测试。"""

from __future__ import annotations

from pathlib import Path

from backtest.paper_trading import PaperTradingStore
from data.calendar import TradingCalendar
from runtime.market_open_paper_execution import MARKET_OPEN_EXECUTION_ID
from runtime.paper_execution_sla import audit_paper_execution_sla
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_paper_execution_sla_passes_for_same_day_terminal_orders(tmp_path: Path) -> None:
    """计划日完成成交和市场约束拒单都代表系统已按 T+1 尝试执行。"""
    paths = _paths(tmp_path)
    store, account_id = _account(paths)
    filled_id = store.record_pending_order(
        account_id, "2026-07-24", "000001.SZ", "平安银行", "BUY", 10.0, 100, "signal=2026-07-23"
    )
    store.fill_order(filled_id, "2026-07-24", 10.0)
    rejected_id = store.record_pending_order(
        account_id, "2026-07-24", "000002.SZ", "万科A", "BUY", 10.0, 100, "signal=2026-07-23"
    )
    store.conn.execute(
        "UPDATE paper_order SET status = 'REJECTED', fill_date = ? WHERE id = ?",
        ("2026-07-24", rejected_id),
    )
    store.conn.commit()
    store.close()
    _record_execution_run(paths, "20260724", "WARNING")

    result = audit_paper_execution_sla(paths, "20260724", _calendar())

    assert result.status == "SUCCESS"
    assert result.due_orders == 2
    assert result.filled_orders == 1
    assert result.rejected_orders == 1
    assert result.pending_orders == 0


def test_paper_execution_sla_fails_when_job_did_not_run(tmp_path: Path) -> None:
    """即使没有调仓单，交易日也必须留下开盘任务运行证据。"""
    paths = _paths(tmp_path)

    result = audit_paper_execution_sla(paths, "20260724", _calendar())

    assert result.status == "FAILED"
    assert "market_open_paper_execution 未运行" in result.issues


def test_paper_execution_sla_fails_for_pending_due_order(tmp_path: Path) -> None:
    """到期单仍为 PENDING 说明 T+1 链路没有闭环。"""
    paths = _paths(tmp_path)
    store, account_id = _account(paths)
    store.record_pending_order(
        account_id, "2026-07-24", "000001.SZ", "平安银行", "BUY", 10.0, 100, "signal=2026-07-23"
    )
    store.close()
    _record_execution_run(paths, "20260724", "BLOCKED")

    result = audit_paper_execution_sla(paths, "20260724", _calendar())

    assert result.status == "FAILED"
    assert result.pending_orders == 1
    assert any("状态异常" in issue for issue in result.issues)
    assert any("到期委托未处理" in issue for issue in result.issues)


def test_paper_execution_sla_detects_cross_day_catch_up(tmp_path: Path) -> None:
    """昨日到期单今天才处理必须留为延迟执行，而不能冒充准时成交。"""
    paths = _paths(tmp_path)
    store, account_id = _account(paths)
    order_id = store.record_pending_order(
        account_id, "2026-07-23", "000001.SZ", "平安银行", "BUY", 10.0, 100, "signal=2026-07-22"
    )
    store.fill_order(order_id, "2026-07-24", 10.0)
    store.close()
    _record_execution_run(paths, "20260724", "SUCCESS")

    result = audit_paper_execution_sla(paths, "20260724", _calendar())

    assert result.status == "FAILED"
    assert result.late_orders == 1
    assert any("跨交易日" in issue for issue in result.issues)


def test_paper_execution_sla_skips_non_trading_day(tmp_path: Path) -> None:
    """非交易日不要求产生模拟撮合运行记录。"""
    paths = _paths(tmp_path)

    result = audit_paper_execution_sla(paths, "20260725", _calendar())

    assert result.status == "NOT_APPLICABLE"
    assert result.issues == ()


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    return paths


def _account(paths: RuntimePaths) -> tuple[PaperTradingStore, int]:
    store = PaperTradingStore(paths.paper_trading_path)
    account_id = store.create_account("测试策略", "test_strategy", 100_000.0, "510300", "沪深300", "2026-07-23")
    return store, account_id


def _record_execution_run(paths: RuntimePaths, trade_date: str, status: str) -> None:
    SystemRepository(paths.system_state_path).record_strategy_run(
        MARKET_OPEN_EXECUTION_ID,
        trade_date,
        status,
        paths.runs_dir / trade_date,
        "test",
    )


def _calendar() -> TradingCalendar:
    return TradingCalendar(["2026-07-23", "2026-07-24"])
