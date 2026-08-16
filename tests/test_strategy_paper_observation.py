"""按策略隔离的Paper观察账本测试。"""

from __future__ import annotations

from pathlib import Path

from backtest.paper_trading import PaperTradingStore
from data.calendar import TradingCalendar
from runtime.market_open_paper_execution import MARKET_OPEN_EXECUTION_ID
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_paper_observation import (
    StrategyPaperObservation,
    StrategyPaperObservationRepository,
    audit_strategy_paper_observation,
)


def test_observation_starts_after_account_registration_date(tmp_path: Path) -> None:
    """注册当日尚未经历开盘撮合，不能虚增观察天数。"""
    paths = _paths(tmp_path)
    store = PaperTradingStore(paths.paper_trading_path)
    store.create_account("候选", "candidate", 100_000, "510300", "沪深300", "2026-07-24")
    store.close()

    result = audit_strategy_paper_observation(
        paths,
        "candidate",
        "20260724",
        TradingCalendar(["2026-07-24"]),
    )

    assert result.status == "NOT_APPLICABLE"


def test_observation_filters_orders_by_strategy_account(tmp_path: Path) -> None:
    """其他策略的未处理订单不能污染候选策略SLA。"""
    paths = _paths(tmp_path)
    store = PaperTradingStore(paths.paper_trading_path)
    candidate = store.create_account("候选", "candidate", 100_000, "510300", "沪深300", "2026-07-23")
    other = store.create_account("其他", "other", 100_000, "510300", "沪深300", "2026-07-23")
    order_id = store.record_pending_order(
        candidate, "2026-07-24", "000001.SZ", "平安银行", "BUY", 10.0, 100, ""
    )
    store.fill_order(order_id, "2026-07-24", 10.0)
    store.record_pending_order(
        other, "2026-07-24", "000002.SZ", "万科A", "BUY", 10.0, 100, ""
    )
    store.close()
    repository = SystemRepository(paths.system_state_path)
    for run_id in ("candidate", MARKET_OPEN_EXECUTION_ID):
        repository.record_strategy_run(
            run_id, "20260724", "SUCCESS", paths.runs_dir / "20260724", "ok"
        )

    result = audit_strategy_paper_observation(
        paths,
        "candidate",
        "20260724",
        TradingCalendar(["2026-07-23", "2026-07-24"]),
    )

    assert result.status == "SUCCESS"
    assert result.due_orders == 1
    assert result.filled_orders == 1
    assert result.pending_orders == 0


def test_progress_is_isolated_by_strategy(tmp_path: Path) -> None:
    """每个候选必须独立累计连续20日，不能借用平台总成功天数。"""
    repository = StrategyPaperObservationRepository(tmp_path / "system.sqlite")
    calendar = TradingCalendar(["2026-07-23", "2026-07-24"])
    for strategy_id, statuses in {
        "candidate": ["SUCCESS", "SUCCESS"],
        "other": ["FAILED", "SUCCESS"],
    }.items():
        for trade_date, status in zip(["20260723", "20260724"], statuses):
            repository.record(
                StrategyPaperObservation(
                    strategy_id, trade_date, status, "SUCCESS", "SUCCESS",
                    0, 0, 0, 0, 0, 0, (),
                )
            )

    assert repository.progress("candidate", calendar=calendar)["current_streak"] == 2
    assert repository.progress("other", calendar=calendar)["current_streak"] == 1


def _paths(tmp_path: Path) -> RuntimePaths:
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    return paths
