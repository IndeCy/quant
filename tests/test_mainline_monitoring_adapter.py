"""主线链动策略监控适配测试。"""

from pathlib import Path

from backtest.paper_trading import PaperTradingStore
from monitoring.mainline_adapter import sync_mainline_chain_monitoring
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository


def test_sync_mainline_chain_monitoring_writes_strategy_metrics_and_runs(tmp_path: Path) -> None:
    """主线链动模拟盘快照应资产化为统一监控曲线和运行记录。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    store = PaperTradingStore(paths.paper_trading_path)
    account_id = store.create_account(
        strategy_name="主线链动策略",
        strategy_code="Mainline_Chain_Momentum",
        initial_cash=1_000_000,
        benchmark_symbol="000001.SH",
        benchmark_name="上证指数",
        start_date="2026-06-05",
    )
    store.record_daily_snapshot(
        account_id,
        "2026-06-05",
        total_value=1_000_000,
        cash=100_000,
        position_value=900_000,
        strategy_return=0.0,
        benchmark_return=0.0,
        excess_return=0.0,
        strongest_chain="通信AI",
        rebalance_signal="NONE",
        target_symbols=["601138.SH"],
    )
    store.record_daily_snapshot(
        account_id,
        "2026-06-06",
        total_value=1_020_000,
        cash=100_000,
        position_value=920_000,
        strategy_return=0.02,
        benchmark_return=0.01,
        excess_return=0.01,
        strongest_chain="半导体",
        rebalance_signal="REBALANCE",
        target_symbols=["600584.SH"],
    )
    store.close()

    summary = sync_mainline_chain_monitoring(
        paths,
        MonitoringRepository(paths.monitoring_path),
        SystemRepository(paths.system_state_path),
    )

    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("mainline_chain_b")
    latest_run = SystemRepository(paths.system_state_path).latest_run("mainline_chain_b")

    assert summary == {"account_id": 1, "snapshot_count": 2, "latest_trade_date": "20260606"}
    assert history["trade_date"].tolist() == ["20260605", "20260606"]
    assert history.iloc[-1]["strategy_name"] == "主线链动策略"
    assert round(float(history.iloc[-1]["daily_return"]), 6) == 0.02
    assert round(float(history.iloc[-1]["exposure"]), 6) == 0.901961
    assert latest_run is not None
    assert latest_run["trade_date"] == "20260606"
    assert latest_run["message"] == "最强产业链: 半导体, 信号: REBALANCE"
