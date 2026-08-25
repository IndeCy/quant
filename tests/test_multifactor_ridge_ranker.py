"""多因子固定 Ridge 数据与研究门槛测试。"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from examples import multifactor_ridge_ranker_study as study
from examples.multifactor_ridge_ranker_metrics import (
    build_failure_attribution,
)
from ml.cross_sectional_ridge import (
    build_cross_section_features,
    run_annual_expanding_ridge,
)
from runtime.paths import RuntimePaths
from runtime.research_attempts import complete_research_attempt


def test_cross_section_features_do_not_mix_months() -> None:
    """未来月份极端值不能改变历史月份的横截面标准化结果。"""
    frame = pd.DataFrame(
        {
            "signal_date": ["20230131"] * 3 + ["20230228"] * 3,
            "symbol": ["A", "B", "C"] * 2,
            "factor": [1.0, 2.0, 3.0, 10.0, 20.0, 30.0],
        }
    )
    original, columns = build_cross_section_features(frame, ("factor",))
    changed = frame.copy()
    changed.loc[changed["signal_date"].eq("20230228"), "factor"] *= 1000
    transformed, _ = build_cross_section_features(changed, ("factor",))

    left = original[original["signal_date"].eq("20230131")][list(columns)]
    right = transformed[transformed["signal_date"].eq("20230131")][list(columns)]
    pd.testing.assert_frame_equal(left.reset_index(drop=True), right.reset_index(drop=True))


def test_walk_forward_purges_labels_before_each_test_year() -> None:
    """每个测试年训练标签退出日必须严格早于测试信号。"""
    rows = []
    for year in range(2015, 2022):
        for month in [1, 4, 7, 10]:
            signal = f"{year}{month:02d}28"
            exit_date = f"{year}{month + 1:02d}28" if month < 10 else f"{year + 1}0128"
            for index in range(8):
                rows.append(
                    {
                        "signal_date": signal,
                        "symbol": f"S{index}",
                        "feature": float(index + month),
                        "forward_rank": (index + 1) / 8,
                        "forward_return": index / 100,
                        "entry_date": signal,
                        "exit_date": exit_date,
                    }
                )
    frame = pd.DataFrame(rows)

    result = run_annual_expanding_ridge(
        frame,
        ("feature",),
        first_test_year=2019,
    )

    assert (
        result.windows["train_max_exit_date"].astype(str)
        < result.windows["test_signal_start"].astype(str)
    ).all()


def test_definition_has_one_fixed_model_and_no_search() -> None:
    """研究不得根据验证或测试表现选择模型与参数。"""
    model = study.RESEARCH_SPEC.definition["model"]

    assert model == {
        "type": "ridge",
        "alpha": 1.0,
        "model_selection": "none",
        "parameter_search": "none",
    }
    assert study.RESEARCH_SPEC.definition["features"] == study.FEATURES


def test_gate_rejects_no_incremental_sharpe() -> None:
    """Ridge若不能改善同因子等权基线Sharpe就必须淘汰。"""
    metrics = {
        period: {
            "annualized_return": 0.12,
            "max_drawdown": -0.20,
            "sharpe": 0.70,
            "calmar": 0.60,
            "annual_turnover": 5.0,
        }
        for period in ["2019_2021", "2022_2023", "2024_latest", "full_oos"]
    }
    annual = {
        str(year): {"annualized_return": 0.10}
        for year in range(2019, 2027)
    }
    prediction = {"mean_rank_ic": 0.03, "positive_ic_ratio": 0.60}
    coefficients = {
        feature: {"positive_share": 1.0}
        for feature in study.FEATURES
    }
    comparison = {
        study.ML_ID: metrics["full_oos"],
        study.EQUAL_ID: {**metrics["full_oos"], "sharpe": 0.69},
        study.QUALITY_ID: {**metrics["full_oos"], "sharpe": 0.70},
    }

    gate = study.evaluate_gate(
        metrics,
        annual,
        prediction,
        coefficients,
        comparison,
        0.50,
        0.50,
    )

    assert gate["passed"] is False
    assert gate["checks"]["equal_control_sharpe_improves_005"] is False


def test_failure_attribution_detects_top_tail_reversal() -> None:
    """最高预测分组弱于中段时必须明确记录尾部反转。"""
    buckets = pd.DataFrame(
        {
            "bucket": list(range(1, 11)),
            "average_forward_return": [
                0.00,
                0.01,
                0.01,
                0.02,
                0.02,
                0.02,
                0.02,
                0.02,
                0.01,
                0.005,
            ],
        }
    )
    coefficients = {
        feature: {"mean": 0.01}
        for feature in study.FEATURES
    }
    comparison = {
        study.ML_ID: {
            "annual_turnover": 10.0,
            "execution_cost_impact": 0.15,
        },
        study.EQUAL_ID: {
            "annual_turnover": 8.0,
            "execution_cost_impact": 0.10,
        },
    }

    result = build_failure_attribution(
        buckets,
        coefficients,
        comparison,
    )

    assert result["top_tail_weaker_than_middle"] is True
    assert result["top_tail_return_gap"] < 0


def test_same_fingerprint_skips_dataset_build(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """相同定义与数据版本再次运行不能重建大数据集。"""
    paths = RuntimePaths(root=tmp_path)
    paths.ensure_directories()
    for path in [
        paths.base_market_path,
        paths.live_market_increment_path,
        paths.fund_daily_history_path,
        paths.benchmark_increment_path,
        paths.fina_indicator_path,
        paths.income_statement_path,
        paths.balance_sheet_path,
        paths.cashflow_statement_path,
    ]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    attempt = study.begin_research_attempt(
        study.RESEARCH_SPEC,
        paths=paths,
        data_as_of="20260724",
        data_version=study._data_version(paths),
    )
    complete_research_attempt(
        attempt,
        metrics={"gate": {"passed": False}},
        outcome="REJECTED",
        decision_reason="测试记录",
    )

    def fail_if_calculated(*_args, **_kwargs):
        raise AssertionError("命中指纹后不得构造数据集")

    monkeypatch.setattr(study, "_calculate", fail_if_calculated)

    result = study.run_study(paths, "20260724")

    assert result["reused"] is True
