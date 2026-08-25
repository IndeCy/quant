"""策略实例批量运行器测试。"""

from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pandas as pd
import pytest

from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.strategy_batch_runner import (
    _sync_local_paper_from_artifacts,
    _with_push_args,
    _with_run_args,
    build_default_strategy_executor_registry,
    run_enabled_strategy_instances,
)
from runtime.strategy_executor_registry import StrategyExecutionContext
from strategies.opportunity_observer_runner import OpportunityObserverComputation


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
    account_snapshot = repository.load_account_snapshot("paper_test")
    assert account_snapshot is not None
    assert account_snapshot["target_position_weight"] == pytest.approx(1.0)


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


def test_strategy_batch_dispatches_opportunity_observer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """批处理应能分发观察策略模板。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    repository = SystemRepository(paths.system_state_path)
    repository.upsert_strategy_instance(
        {
            "strategy_id": "innovative_drug_globalization_observer_v0",
            "name": "创新药出海观察策略 V0",
            "template_id": "opportunity_observer",
            "status": "research_observation",
            "enabled": True,
            "universe": "opportunity_theme:innovative_drug_globalization",
            "filters": [],
            "factors": [],
            "construction": {"top_n": 5},
            "benchmark": "510300",
            "config": {"theme_id": "innovative_drug_globalization"},
        }
    )
    monkeypatch.setattr(
        "runtime.strategy_batch_runner.compute_opportunity_observer_instance",
        lambda instance, paths, trade_date=None: OpportunityObserverComputation(
            result={
                "strategy_id": instance["strategy_id"],
                "trade_date": trade_date,
                "selected_count": 3,
                "nav": 1.0,
            },
            selected=[],
            excluded=[],
            target_weights={},
            current_prices={},
            monitoring_frame=pd.DataFrame(),
        ),
    )
    monkeypatch.setattr(
        "runtime.strategy_batch_runner.persist_opportunity_observer_instance",
        lambda instance, paths, computation: computation.result,
    )

    result = run_enabled_strategy_instances(paths)

    assert result["success_count"] == 1
    assert result["results"][0]["message"] == "observation selected 3 symbols, nav 1.000000"


def test_quality_adapter_returns_standard_target_portfolio(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """冻结 Quality 应在当前进程返回目标组合，不再依赖子进程 CSV 回读。"""
    paths = RuntimePaths(tmp_path / "runtime")
    persisted: list[str] = []
    monkeypatch.setattr(
        "runtime.strategy_batch_runner.compute_quality_overlay_instance",
        lambda instance, paths, trade_date: SimpleNamespace(
            result={
                "strategy_id": instance["strategy_id"],
                "trade_date": trade_date,
                "selected_count": 2,
                "target_weights": {"000001.SZ": 0.5, "000002.SZ": 0.5},
                "nav": 1.2,
            }
        ),
    )
    registry = build_default_strategy_executor_registry()

    computation = registry.compute(
        {
            "strategy_id": "quality_overlay",
            "template_id": "factor_topn_monthly",
            "config": {"adapter": "quality_overlay_compat"},
        },
        StrategyExecutionContext(paths=paths, trade_date="20260715"),
    )

    result = computation.result
    assert result.target_portfolio is not None
    assert result.target_portfolio.weights == {"000001.SZ": 0.5, "000002.SZ": 0.5}
    assert persisted == []


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


def test_batch_runner_appends_requested_run_date_to_compat_script() -> None:
    """兼容策略脚本必须收到补跑日期，避免记录落到当天。"""
    command = _with_run_args(["python", "script.py"], "20260707", True, "https://example.invalid/token")

    assert command == [
        "python",
        "script.py",
        "--run-date",
        "20260707",
        "--push",
        "--bark-url",
        "https://example.invalid/token",
    ]


def test_batch_runner_syncs_portfolio_artifact_to_local_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """策略产物生成后，应统一进入 LocalPaperBroker，而不是只停留在日报文件。"""
    paths = RuntimePaths(tmp_path / "runtime")
    paths.ensure_directories()
    run_dir = paths.runs_dir / "20260709"
    run_dir.mkdir(parents=True)
    (run_dir / "paper_test_portfolio_snapshot.csv").write_text(
        "symbol,name,target_weight\n000001.SZ,平安银行,0.5\n",
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "runtime.strategy_batch_runner.load_live_market_for_symbols",
        lambda paths, trade_date, symbols, names=None: calls.append({"symbols": symbols, "names": names}) or __import__("pandas").DataFrame(
            [
                {
                    "trade_date": "20260709",
                    "symbol": "000001.SZ",
                    "name": "平安银行",
                    "open": 10.0,
                    "high": 10.2,
                    "low": 9.9,
                    "close": 10.1,
                    "volume": 100000,
                    "amount": 1000000,
                    "is_suspended": False,
                    "limit_up": False,
                    "limit_down": False,
                }
            ]
        ),
    )

    message = _sync_local_paper_from_artifacts(
        {
            "strategy_id": "paper_test",
            "name": "Paper Test",
            "benchmark": "510300",
            "config": {"initial_capital": 100000.0},
        },
        paths,
        "20260709",
    )

    assert "paper_broker created=1" in message
    assert calls[0]["symbols"] == ["000001.SZ"]
    account_snapshot = SystemRepository(paths.system_state_path).load_account_snapshot("paper_test")
    assert account_snapshot is not None
    assert account_snapshot["trade_date"] == "20260709"
    assert account_snapshot["target_position_weight"] == pytest.approx(0.5)
    assert account_snapshot["positions"][0]["symbol"] == "000001.SZ"


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
