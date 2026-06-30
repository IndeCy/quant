"""策略实例批量运行器测试。"""

from pathlib import Path
import sqlite3

from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import run_enabled_strategy_instances


def test_batch_runner_runs_enabled_factor_topn_instances(tmp_path: Path) -> None:
    """批量运行器应从策略实例表发现并运行 enabled 因子策略。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_factor_scores(paths)
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_strategy_instance(
        {
            "strategy_id": "paper_test",
            "name": "Paper Test",
            "template_id": "factor_topn_monthly",
            "status": "paper",
            "enabled": True,
            "universe": "all_a",
            "filters": [],
            "factors": [{"factor_id": "roa", "weight": 1.0, "transform": "winsorize_zscore"}],
            "construction": {"top_n": 20, "weighting": "equal_weight"},
            "risk_overlay": "",
            "benchmark": "510300",
        }
    )

    summary = run_enabled_strategy_instances(paths)
    latest = repository.latest_run("paper_test")

    assert summary["enabled_count"] == 1
    assert summary["success_count"] == 1
    assert latest is not None
    assert latest["status"] == "SUCCESS"
    assert "selected 2 symbols" in latest["message"]


def _seed_factor_scores(paths: RuntimePaths) -> None:
    with sqlite3.connect(paths.factor_scores_path) as con:
        con.execute("CREATE TABLE factor_scores(trade_date TEXT, symbol TEXT, factor_id TEXT, value REAL)")
        con.executemany(
            "INSERT INTO factor_scores VALUES (?, ?, ?, ?)",
            [
                ("20260630", "000001.SZ", "roa", 0.10),
                ("20260630", "000002.SZ", "roa", 0.20),
            ],
        )
