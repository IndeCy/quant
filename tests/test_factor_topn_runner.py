"""因子 TopN 策略实例运行测试。"""

from pathlib import Path
import sqlite3

from monitoring.repository import MonitoringRepository
from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from strategies.factor_topn_runner import run_factor_topn_monthly_instance


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

    result = run_factor_topn_monthly_instance(instance, paths)
    latest = SystemRepository(paths.system_state_path).latest_run("quality_roa_ocf_v2")
    history = MonitoringRepository(paths.monitoring_path).load_strategy_history("quality_roa_ocf_v2")

    assert result["selected_count"] == 2
    assert result["symbols"] == ["000002.SZ", "000001.SZ"]
    assert latest is not None
    assert latest["status"] == "SUCCESS"
    assert history.iloc[-1]["strategy_name"] == "Quality ROA OCF V2"


def _seed_factor_scores(paths: RuntimePaths) -> None:
    with sqlite3.connect(paths.factor_scores_path) as con:
        con.execute(
            """
            CREATE TABLE factor_scores (
                trade_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                factor_id TEXT NOT NULL,
                value REAL NOT NULL
            )
            """
        )
        con.executemany(
            "INSERT INTO factor_scores VALUES (?, ?, ?, ?)",
            [
                ("20260630", "000001.SZ", "roa", 0.10),
                ("20260630", "000001.SZ", "ocf_to_or", 0.20),
                ("20260630", "000002.SZ", "roa", 0.12),
                ("20260630", "000002.SZ", "ocf_to_or", 0.30),
                ("20260630", "000003.SZ", "roa", 0.02),
                ("20260630", "000003.SZ", "ocf_to_or", 0.05),
            ],
        )
