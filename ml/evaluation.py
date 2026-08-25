"""机器学习信号的选择、收益分层和晋级诊断。"""

from __future__ import annotations

import pandas as pd

from portfolio.topn import build_topn_selections


def build_prediction_selections(
    predictions: pd.DataFrame,
    *,
    top_n: int = 20,
) -> tuple[dict[str, list[str]], pd.DataFrame]:
    """把模型连续分数交给通用组合层生成 TopN。"""
    required = ["signal_date", "symbol", "prediction"]
    missing = [column for column in required if column not in predictions.columns]
    if missing:
        raise ValueError(f"prediction frame missing columns: {missing}")
    return build_topn_selections(predictions, "prediction", top_n)


def build_return_bucket_diagnostics(
    predictions: pd.DataFrame,
    *,
    bucket_count: int = 10,
) -> pd.DataFrame:
    """按每月预测排名分桶，检查收益是否具有横截面单调性。"""
    if bucket_count < 2:
        raise ValueError("bucket_count must be at least two")
    data = predictions.dropna(subset=["prediction", "forward_return"]).copy()
    data["bucket"] = data.groupby("signal_date")["prediction"].transform(
        lambda values: pd.qcut(
            values.rank(method="first"),
            bucket_count,
            labels=False,
            duplicates="drop",
        )
    )
    result = (
        data.groupby("bucket", as_index=False)
        .agg(
            average_forward_return=("forward_return", "mean"),
            win_rate=("forward_return", lambda values: float(values.gt(0).mean())),
            sample_count=("forward_return", "size"),
        )
        .sort_values("bucket")
    )
    result["bucket"] = result["bucket"].astype(int) + 1
    return result


def select_model_on_validation(
    model_metrics: pd.DataFrame,
) -> str:
    """按预先冻结规则选择模型，测试集字段不得参与。"""
    required = [
        "model_id",
        "validation_mean_rank_ic",
        "validation_sharpe",
        "validation_max_drawdown",
        "validation_turnover",
    ]
    missing = [column for column in required if column not in model_metrics.columns]
    if missing:
        raise ValueError(f"model selection metrics missing columns: {missing}")
    forbidden = [column for column in model_metrics.columns if column.startswith("test_selection_")]
    if forbidden:
        raise ValueError(f"test metrics cannot participate in model selection: {forbidden}")
    ranked = model_metrics.sort_values(
        [
            "validation_mean_rank_ic",
            "validation_sharpe",
            "validation_max_drawdown",
            "validation_turnover",
            "model_id",
        ],
        ascending=[False, False, False, True, True],
        kind="stable",
    )
    if ranked.empty:
        raise ValueError("no model candidates")
    return str(ranked.iloc[0]["model_id"])


def evaluate_promotion_gate(
    metrics: dict[str, float],
) -> dict[str, object]:
    """用冻结阈值判断研究模型是否有资格进入 Paper。"""
    checks = {
        "test_rank_ic": metrics.get("test_mean_rank_ic", 0.0) > 0.02,
        "positive_ic_months": metrics.get("test_positive_ic_ratio", 0.0) > 0.52,
        "after_cost_sharpe": metrics.get("test_sharpe", float("-inf")) > metrics.get(
            "baseline_test_sharpe", float("inf")
        ),
        "drawdown": metrics.get("test_max_drawdown", -1.0)
        >= metrics.get("baseline_test_max_drawdown", 0.0) - 0.05,
        "turnover": metrics.get("test_turnover", float("inf"))
        <= metrics.get("baseline_test_turnover", 0.0) * 1.5,
    }
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
    }
