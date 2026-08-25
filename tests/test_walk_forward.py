"""Walk-Forward 验证器测试。"""

from pathlib import Path

import pandas as pd

from runtime.paths import RuntimePaths
from runtime.repository import SystemRepository
from runtime.walk_forward import (
    WalkForwardWindow,
    run_walk_forward_experiment,
    run_walk_forward_validation,
    select_best_parameter,
)


def _sample_metrics() -> pd.DataFrame:
    """构造最小参数表现表，避免单测依赖真实行情。"""
    return pd.DataFrame(
        [
            {
                "window": "stage1",
                "sample": "train",
                "parameter_id": "A",
                "annual_return": 0.12,
                "max_drawdown": -0.30,
                "sharpe": 0.80,
                "calmar": 0.40,
                "average_exposure": 0.70,
            },
            {
                "window": "stage1",
                "sample": "train",
                "parameter_id": "B",
                "annual_return": 0.11,
                "max_drawdown": -0.20,
                "sharpe": 0.80,
                "calmar": 0.40,
                "average_exposure": 1.00,
            },
            {
                "window": "stage1",
                "sample": "validation",
                "parameter_id": "B",
                "annual_return": 0.08,
                "max_drawdown": -0.16,
                "sharpe": 0.60,
                "calmar": 0.50,
                "average_exposure": 1.00,
            },
            {
                "window": "stage2",
                "sample": "train",
                "parameter_id": "C",
                "annual_return": 0.16,
                "max_drawdown": -0.40,
                "sharpe": 0.90,
                "calmar": 0.40,
                "average_exposure": 0.30,
            },
            {
                "window": "stage2",
                "sample": "validation",
                "parameter_id": "C",
                "annual_return": 0.04,
                "max_drawdown": -0.10,
                "sharpe": 0.30,
                "calmar": 0.40,
                "average_exposure": 0.30,
            },
        ]
    )


def test_select_best_parameter_uses_locked_sort_order() -> None:
    """选参必须固定为夏普、Calmar、回撤、仓位四级排序。"""
    train = _sample_metrics()[lambda frame: frame["sample"].eq("train") & frame["window"].eq("stage1")]

    best = select_best_parameter(train)

    assert best["parameter_id"] == "B"


def test_walk_forward_validation_freezes_train_selected_parameter() -> None:
    """验证集只能评估训练集选出的参数，不能反向看验证集择优。"""
    windows = [
        WalkForwardWindow(
            window_id="stage1",
            train_start="2015-01-01",
            train_end="2018-12-31",
            validation_start="2019-01-01",
            validation_end="2021-12-31",
        ),
        WalkForwardWindow(
            window_id="stage2",
            train_start="2015-01-01",
            train_end="2021-12-31",
            validation_start="2022-01-01",
            validation_end="2026-12-31",
        ),
    ]

    result = run_walk_forward_validation(_sample_metrics(), windows)

    assert result["selected_parameters"].to_dict("records") == [
        {"window": "stage1", "parameter_id": "B"},
        {"window": "stage2", "parameter_id": "C"},
    ]
    validation_rows = result["walk_forward"].query("sample == 'validation'")
    assert validation_rows["parameter_id"].tolist() == ["B", "C"]


def test_walk_forward_experiment_registers_artifacts(tmp_path: Path) -> None:
    """Walk-Forward 实验应生成报告并进入实验仓库。"""
    paths = RuntimePaths(tmp_path / "runtime")
    windows = [
        WalkForwardWindow(
            window_id="stage1",
            train_start="2015-01-01",
            train_end="2018-12-31",
            validation_start="2019-01-01",
            validation_end="2021-12-31",
        )
    ]

    result = run_walk_forward_experiment(
        paths=paths,
        experiment_id="quality_walk_forward_research",
        name="Quality Walk Forward Research",
        metric_frame=_sample_metrics(),
        windows=windows,
        run_date="20260702",
        message="固定排序规则验证",
    )
    detail = SystemRepository(paths.system_state_path).load_experiment_detail("quality_walk_forward_research")

    assert result["status"] == "SUCCESS"
    assert Path(result["summary_path"]).exists()
    assert detail is not None
    assert detail["latest_run"]["metrics"]["validation_windows"] == 1
    assert {artifact["artifact_type"] for artifact in detail["latest_run"]["artifacts"]} == {
        "summary",
        "selected_parameters",
        "walk_forward",
        "metrics",
    }
