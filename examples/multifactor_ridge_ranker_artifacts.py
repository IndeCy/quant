"""多因子 Ridge 研究产物归档。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import duckdb
import joblib
import pandas as pd

from examples.multifactor_ridge_ranker_report import render_report
from examples.quality_risk_layer_research import RiskLayerRun
from runtime.experiment_runner import ExperimentArtifact
from runtime.research_attempts import (
    ResearchAttempt,
    complete_research_attempt,
)


def complete_attempt(
    attempt: ResearchAttempt,
    result: dict[str, Any],
    context: dict[str, Any],
) -> None:
    """保存模型、点时数据、预测、净值和解释性产物。"""
    output = attempt.output_dir
    summary = output / "summary.md"
    summary.write_text(render_report(result), encoding="utf-8")
    dataset_path = output / "dataset.parquet"
    predictions_path = output / "walk_forward_predictions.parquet"
    _write_parquet(context["dataset"].frame, dataset_path)
    _write_parquet(context["walk"].predictions, predictions_path)
    windows_path = output / "walk_forward_windows.csv"
    coefficients_path = output / "coefficients.csv"
    holdings_path = output / "holdings.csv"
    bucket_path = output / "bucket_diagnostics.csv"
    curves_path = output / "curves.csv"
    model_path = output / "model.joblib"
    context["walk"].windows.to_csv(windows_path, index=False)
    context["walk"].coefficients.to_csv(coefficients_path, index=False)
    context["holdings"].to_csv(holdings_path, index=False)
    context["bucket"].to_csv(bucket_path, index=False)
    _build_curves(context["runs"]).to_csv(curves_path, index=False)
    joblib.dump(context["walk"].final_estimator, model_path)
    passed = bool(result["gate"]["passed"])
    complete_research_attempt(
        attempt,
        metrics=result,
        outcome="PASSED_RESEARCH_GATE" if passed else "REJECTED",
        decision_reason=(
            "固定Ridge通过严格样本外门槛，仅进入独立前瞻确认"
            if passed
            else "固定Ridge未通过样本外门槛，不注册生产策略"
        ),
        artifacts=[
            ExperimentArtifact("summary", summary, "样本外研究报告"),
            ExperimentArtifact("dataset", dataset_path, "点时训练数据"),
            ExperimentArtifact("predictions", predictions_path, "Walk Forward预测"),
            ExperimentArtifact("walk_forward_windows", windows_path, "训练测试窗口"),
            ExperimentArtifact("coefficients", coefficients_path, "逐年模型系数"),
            ExperimentArtifact("holdings", holdings_path, "月度Top20"),
            ExperimentArtifact("bucket_diagnostics", bucket_path, "预测分桶"),
            ExperimentArtifact("curves", curves_path, "策略净值"),
            ExperimentArtifact("model", model_path, "最后一期研究模型"),
        ],
    )


def _build_curves(runs: dict[str, RiskLayerRun]) -> pd.DataFrame:
    curves = {
        name: run.result.daily_values
        / float(run.result.daily_values.iloc[0])
        for name, run in runs.items()
    }
    return pd.DataFrame(curves).rename_axis("trade_date").reset_index()


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.register("artifact_frame", frame)
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(
            f"COPY artifact_frame TO '{escaped}' "
            "(FORMAT PARQUET, COMPRESSION ZSTD)"
        )
    finally:
        connection.close()
