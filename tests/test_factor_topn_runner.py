"""因子 TopN 策略实例运行测试。"""

from pathlib import Path
import sqlite3

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from strategies.factor_topn_runner import (
    compute_factor_topn_monthly_instance,
    persist_factor_topn_monthly_instance,
    run_factor_topn_monthly_instance,
)


def test_factor_topn_runner_selects_weighted_top_names(tmp_path: Path) -> None:
    """因子组合实例应能从标准因子分数表选股并生成观测资产。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_factor_scores(paths)
    instance = {
        "strategy_id": "quality_roa_ocf_v2",
        "name": "Quality ROA OCF V2",
        "factors": [
            {"factor_id": "roa", "weight": 0.6, "transform": "zscore"},
            {"factor_id": "ocf_to_or", "weight": 0.4, "transform": "zscore"},
        ],
        "construction": {"top_n": 2, "weighting": "equal_weight"},
        "benchmark": "510300",
    }

    computation = compute_factor_topn_monthly_instance(instance, paths)

    assert not paths.system_state_path.exists()
    assert not paths.monitoring_path.exists()
    assert not (paths.runs_dir / "20260630").exists()

    result = persist_factor_topn_monthly_instance(instance, paths, computation)
    latest = SystemRepository(paths.system_state_path).latest_run("quality_roa_ocf_v2")
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("quality_roa_ocf_v2")

    assert result["selected_count"] == 2
    assert result["symbols"] == ["000002.SZ", "000001.SZ"]
    assert latest is not None
    assert latest["status"] == "SUCCESS"
    assert history.iloc[-1]["strategy_name"] == "Quality ROA OCF V2"


def test_factor_topn_runner_keeps_continuous_nav_from_prices(tmp_path: Path) -> None:
    """连续运行同一策略实例时，应按上一期持仓价格变化形成历史净值曲线。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_factor_scores(paths, trade_date="20260629")
    _seed_prices(paths, "20260629", {"000001.SZ": 10.0, "000002.SZ": 20.0, "000003.SZ": 5.0})
    instance = {
        "strategy_id": "quality_roa_ocf_v2",
        "name": "Quality ROA OCF V2",
        "factors": [
            {"factor_id": "roa", "weight": 0.6, "transform": "zscore"},
            {"factor_id": "ocf_to_or", "weight": 0.4, "transform": "zscore"},
        ],
        "construction": {"top_n": 2, "weighting": "equal_weight"},
        "benchmark": "510300",
    }
    run_factor_topn_monthly_instance(instance, paths)

    _seed_factor_scores(paths, trade_date="20260630")
    _seed_prices(paths, "20260630", {"000001.SZ": 11.0, "000002.SZ": 22.0, "000003.SZ": 5.0})
    run_factor_topn_monthly_instance(instance, paths)
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("quality_roa_ocf_v2")

    assert history["trade_date"].tolist() == ["20260629", "20260630"]
    assert round(float(history.iloc[-1]["nav"]), 6) == 1.1
    assert round(float(history.iloc[-1]["daily_return"]), 6) == 0.1


def _seed_factor_scores(paths: RuntimePaths, trade_date: str = "20260630") -> None:
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
        con.execute("DELETE FROM factor_scores WHERE trade_date = ?", [trade_date])
        con.executemany(
            "INSERT INTO factor_scores VALUES (?, ?, ?, ?)",
            [
                (trade_date, "000001.SZ", "roa", 0.10),
                (trade_date, "000001.SZ", "ocf_to_or", 0.20),
                (trade_date, "000002.SZ", "roa", 0.12),
                (trade_date, "000002.SZ", "ocf_to_or", 0.30),
                (trade_date, "000003.SZ", "roa", 0.02),
                (trade_date, "000003.SZ", "ocf_to_or", 0.05),
            ],
        )


def _seed_prices(paths: RuntimePaths, trade_date: str, prices: dict[str, float]) -> None:
    with sqlite3.connect(paths.factor_scores_path) as con:
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
            "INSERT OR REPLACE INTO daily_prices VALUES (?, ?, ?)",
            [(trade_date, symbol, close) for symbol, close in prices.items()],
        )
