"""策略实例批量运行器测试。"""

from pathlib import Path
import sqlite3

import pytest

from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import _with_push_args, run_enabled_strategy_instances


def test_batch_runner_runs_enabled_factor_topn_instances(tmp_path: Path) -> None:
    """批量运行器应从策略实例表发现并运行 enabled 因子策略。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_factor_scores(paths)
    repository = SystemRepository(paths.system_state_path)
    _seed_factor_contract(repository)
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


def test_batch_runner_skips_enabled_research_instances(tmp_path: Path) -> None:
    """研究态策略即使 enabled=True 也不应进入每日批处理。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    _seed_factor_scores(paths)
    repository = SystemRepository(paths.system_state_path)
    _seed_factor_contract(repository)
    repository.upsert_strategy_instance(
        {
            "strategy_id": "research_test",
            "name": "Research Test",
            "template_id": "factor_topn_monthly",
            "status": "research",
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

    assert summary["enabled_count"] == 0
    assert repository.latest_run("research_test") is None


@pytest.mark.parametrize(
    ("push", "bark_url", "expected"),
    [
        (False, "", ["python", "script.py"]),
        (True, "", ["python", "script.py"]),
        (True, "https://example.invalid/token", ["python", "script.py", "--push", "--bark-url", "https://example.invalid/token"]),
    ],
)
def test_batch_runner_appends_push_args(push: bool, bark_url: str, expected: list[str]) -> None:
    """批处理开启通知时，应把统一 Bark 配置透传给兼容策略脚本。"""
    assert _with_push_args(["python", "script.py"], push, bark_url) == expected


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


def _seed_factor_contract(repository: SystemRepository) -> None:
    repository.upsert_factor_contract(
        {
            "factor_id": "roa",
            "name": "ROA",
            "category": "quality",
            "direction": "higher_is_better",
            "source": "fina_indicator",
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
