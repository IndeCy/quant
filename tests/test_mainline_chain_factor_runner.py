"""主线链动原生因子组合 runner 测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest.cache import MarketDataCache
from examples.compare_chain_stock_selection import build_default_chain_definitions
from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_instance_catalog import register_builtin_strategy_instances
from strategies.mainline_chain_factor_runner import (
    compute_factor_chain_rotation_instance,
    persist_factor_chain_rotation_instance,
)


def test_mainline_chain_factor_runner_writes_monitoring_and_artifacts(tmp_path: Path) -> None:
    """原生主线策略应使用本地标准缓存完成回测、持仓和运行产物登记。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_market_cache(paths)
    repository = SystemRepository(paths.system_state_path)
    register_builtin_strategy_instances(repository)
    instance = repository.load_strategy_instance("mainline_chain_factor_v1")

    computation = compute_factor_chain_rotation_instance(instance, paths)

    assert repository.latest_run("mainline_chain_factor_v1") is None
    assert not paths.monitoring_path.exists()
    assert not (paths.runs_dir / computation.result["trade_date"]).exists()

    result = persist_factor_chain_rotation_instance(instance, paths, computation)

    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("mainline_chain_factor_v1")
    state = repository.load_strategy_instance_state("mainline_chain_factor_v1")
    run = repository.latest_run("mainline_chain_factor_v1")
    artifacts = repository.list_run_artifacts("mainline_chain_factor_v1", result["trade_date"])
    run_dir = paths.runs_dir / result["trade_date"]
    report = (run_dir / "mainline_chain_factor_v1_daily_report.md").read_text(encoding="utf-8")
    metrics = (run_dir / "mainline_chain_factor_v1_strategy_metrics.json").read_text(encoding="utf-8")

    assert result["selected_count"] > 0
    assert result["rows"] == len(history)
    assert state["trade_date"] == result["trade_date"]
    assert len(state["holdings"]) == result["selected_count"]
    assert run is not None
    assert run["status"] == "SUCCESS"
    assert {item["report_type"] for item in artifacts} == {
        "daily_report",
        "portfolio_snapshot",
        "rebalance_plan",
        "strategy_metrics",
    }
    assert "当前仓位" in report
    assert "当日收益" in report
    assert "当前回撤" in report
    assert "风险状态" in report
    assert "daily_return" in metrics
    assert "current_drawdown" in metrics
    assert "target_exposure" in metrics
    assert "risk_state" in metrics


def _seed_market_cache(paths: RuntimePaths) -> None:
    cache = MarketDataCache(paths.data_dir / "market_cache.sqlite3")
    try:
        dates = pd.bdate_range("2025-01-02", periods=260)
        chains = build_default_chain_definitions()
        for chain_index, chain in enumerate(chains):
            proxy_growth = 0.08 + chain_index * 0.02
            if chain.name == "通信AI":
                proxy_growth = 0.45
            cache.upsert_bars("tushare", chain.proxy_symbol, "1d", "qfq", _bars(dates, 10.0, proxy_growth))
            for stock_index, stock in enumerate(chain.stocks):
                growth = proxy_growth + stock_index * 0.04
                cache.upsert_bars("tushare", stock.symbol, "1d", "qfq", _bars(dates, 20.0 + stock_index, growth))
        cache.upsert_bars("tushare", "000001.SH", "1d", "none", _bars(dates, 3000.0, 0.05))
    finally:
        cache.close()


def _bars(dates: pd.DatetimeIndex, start: float, growth: float) -> pd.DataFrame:
    values = [start * (1.0 + growth * i / (len(dates) - 1)) for i in range(len(dates))]
    frame = pd.DataFrame(index=dates)
    frame["close"] = values
    frame["open"] = frame["close"] * 0.995
    frame["high"] = frame["close"] * 1.01
    frame["low"] = frame["close"] * 0.99
    frame["volume"] = 1000000
    frame["amount"] = frame["close"] * frame["volume"]
    return frame
