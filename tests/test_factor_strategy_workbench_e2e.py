"""因子策略工作台端到端测试。"""

from pathlib import Path
import sqlite3

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import run_enabled_strategy_instances


def test_factor_strategy_instance_runs_into_monitoring_curve(tmp_path: Path) -> None:
    """自定义因子策略实例应能被批处理运行，并沉淀连续 NAV 曲线。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_factor_contract(
        {
            "factor_id": "profit_stability",
            "name": "盈利稳定性",
            "category": "quality",
            "direction": "lower_is_better",
            "source": "manual",
            "description": "过去三年ROA波动率越低越好",
            "frequency": "annual",
            "value_type": "numeric",
            "as_of_policy": "financial_announcement",
            "as_of_field": "f_ann_date",
            "effective_date_field": "trade_date",
            "input_datasets": ["fina_indicator_duckdb"],
            "input_fields": ["roa"],
            "output_fields": ["trade_date", "symbol", "factor_value"],
            "status": "active",
        }
    )
    repository.upsert_strategy_instance(
        {
            "strategy_id": "profit_stability_paper",
            "name": "盈利稳定性 Paper",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": [],
            "factors": [{"factor_id": "profit_stability", "weight": 1.0, "transform": "zscore"}],
            "construction": {"top_n": 2, "weighting": "equal_weight"},
            "risk_overlay": "",
            "benchmark": "510300",
        }
    )
    _seed_scores_and_prices(paths, "20260629", {"000001.SZ": 0.2, "000002.SZ": 0.1}, {"000001.SZ": 10, "000002.SZ": 20})

    first = run_enabled_strategy_instances(paths)
    _seed_scores_and_prices(paths, "20260630", {"000001.SZ": 0.2, "000002.SZ": 0.1}, {"000001.SZ": 11, "000002.SZ": 22})
    second = run_enabled_strategy_instances(paths)
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("profit_stability_paper")
    state = repository.load_strategy_instance_state("profit_stability_paper")

    assert first["success_count"] == 1
    assert second["success_count"] == 1
    assert history["trade_date"].tolist() == ["20260629", "20260630"]
    assert round(float(history.iloc[-1]["nav"]), 6) == 1.1
    assert state["trade_date"] == "20260630"
    assert [item["symbol"] for item in state["holdings"]] == ["000001.SZ", "000002.SZ"]


def _seed_scores_and_prices(
    paths: RuntimePaths,
    trade_date: str,
    scores: dict[str, float],
    prices: dict[str, float],
) -> None:
    with sqlite3.connect(paths.factor_scores_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS factor_scores (
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                factor_id TEXT NOT NULL,
                value REAL NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS daily_prices (
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                close REAL NOT NULL,
                PRIMARY KEY (trade_date, symbol)
            )
            """
        )
        con.executemany(
            "INSERT INTO factor_scores VALUES (?, ?, ?, ?)",
            [(trade_date, symbol, "profit_stability", value) for symbol, value in scores.items()],
        )
        con.executemany(
            "INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?)",
            [(trade_date, symbol, close) for symbol, close in prices.items()],
        )
