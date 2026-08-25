"""Quality ML 研究产物落盘和通用实验登记。"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import json
import platform
from pathlib import Path
from typing import Any

import duckdb
import joblib
import pandas as pd
import sklearn

from ml.dataset import QualityMLDataset
from ml.models import fixed_model_definitions
from ml.report import render_quality_ml_report
from ml.split import DatasetSplits
from ml.trainer import TrainedModel, fit_fixed_model
from ml.walk_forward import WalkForwardResult
from runtime.experiment_runner import ExperimentArtifact, record_completed_experiment
from runtime.paths import RuntimePaths
from runtime.research_attempts import ResearchAttempt, complete_research_attempt


def write_quality_ml_experiment(
    *,
    paths: RuntimePaths,
    experiment_id: str,
    as_of_date: str,
    dataset: QualityMLDataset,
    splits: DatasetSplits,
    models: dict[str, TrainedModel],
    selected_model_id: str,
    selected_holdings: pd.DataFrame,
    prediction_metrics: pd.DataFrame,
    test_metrics: pd.DataFrame,
    annual_metrics: pd.DataFrame,
    bucket_diagnostics: pd.DataFrame,
    walk_forward: WalkForwardResult,
    curves: pd.DataFrame,
    promotion_metrics: dict[str, float],
    promotion_gate: dict[str, Any],
    benchmark_label: str,
    attempt: ResearchAttempt | None = None,
) -> dict[str, Any]:
    """写出全部研究产物并登记到已有 Experiment Repository。"""
    timestamp = datetime.now().strftime("%H%M%S")
    run_date = attempt.run_date if attempt else datetime.now().strftime("%Y%m%d")
    output_dir = (
        attempt.output_dir
        if attempt
        else paths.runs_dir / "experiments" / experiment_id / f"{run_date}-{timestamp}"
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "dataset": dataset.spec.to_dict(),
        "split": asdict(splits.definition),
        "model_ids": [definition.model_id for definition in fixed_model_definitions()],
        "selection_rule": "validation RankIC, Sharpe, max drawdown, turnover, model_id",
        "selected_model_id": selected_model_id,
        "risk_overlay": {"window": 20, "threshold": 0.45, "reduced_exposure": 0.30},
        "benchmark_label": benchmark_label,
        "as_of_date": as_of_date,
        "runtime_versions": {
            "python": platform.python_version(),
            "pandas": pd.__version__,
            "scikit_learn": sklearn.__version__,
        },
    }
    report = render_quality_ml_report(
        manifest=dataset.manifest,
        selected_model_id=selected_model_id,
        prediction_metrics=prediction_metrics,
        backtest_metrics=test_metrics,
        annual_metrics=annual_metrics,
        bucket_diagnostics=bucket_diagnostics,
        walk_forward_windows=walk_forward.windows,
        promotion_gate=promotion_gate,
    )
    metrics = {
        "selected_model_id": selected_model_id,
        "dataset": dataset.manifest.to_dict(),
        "promotion": promotion_metrics,
        "gate": promotion_gate,
        "promotion_gate": promotion_gate,
        "test_metrics": test_metrics.to_dict("records"),
    }
    files = _write_files(
        output_dir=output_dir,
        dataset=dataset,
        models=models,
        selected_model_id=selected_model_id,
        selected_holdings=selected_holdings,
        prediction_metrics=prediction_metrics,
        test_metrics=test_metrics,
        annual_metrics=annual_metrics,
        bucket_diagnostics=bucket_diagnostics,
        walk_forward=walk_forward,
        curves=curves,
        config=config,
        metrics=metrics,
        report=report,
    )
    artifacts = [
        ExperimentArtifact(artifact_type, path, title)
        for artifact_type, path, title in files
    ]
    if attempt:
        registered = complete_research_attempt(
            attempt,
            metrics=metrics,
            outcome="PASSED" if promotion_gate.get("status") == "PASS" else "REJECTED",
            decision_reason=(
                "通过固定样本外晋级门槛"
                if promotion_gate.get("status") == "PASS"
                else "固定样本外晋级门槛未通过，不注册生产策略"
            ),
            artifacts=artifacts,
        )
    else:
        registered = record_completed_experiment(
            paths=paths,
            experiment_id=experiment_id,
            name="Quality ML Ranker V0",
            category="machine_learning",
            run_date=run_date,
            output_dir=output_dir,
            config=config,
            metrics=metrics,
            message="固定三因子机器学习排序研究，不修改 Quality V1",
            artifacts=artifacts,
            run_suffix=timestamp,
        )
    return {
        **registered,
        "selected_model_id": selected_model_id,
        "promotion_gate": promotion_gate,
        "dataset_manifest": dataset.manifest.to_dict(),
        "test_metrics": test_metrics.to_dict("records"),
    }


def _write_files(
    *,
    output_dir: Path,
    dataset: QualityMLDataset,
    models: dict[str, TrainedModel],
    selected_model_id: str,
    selected_holdings: pd.DataFrame,
    prediction_metrics: pd.DataFrame,
    test_metrics: pd.DataFrame,
    annual_metrics: pd.DataFrame,
    bucket_diagnostics: pd.DataFrame,
    walk_forward: WalkForwardResult,
    curves: pd.DataFrame,
    config: dict[str, Any],
    metrics: dict[str, Any],
    report: str,
) -> list[tuple[str, Path, str]]:
    static_predictions = []
    for model_id, model in models.items():
        frame = model.predictions.copy()
        frame["model_id"] = model_id
        static_predictions.append(frame)
    definition = next(item for item in fixed_model_definitions() if item.model_id == selected_model_id)
    final_estimator = fit_fixed_model(definition, dataset.trainable_frame())
    files = _artifact_paths(output_dir)
    files["summary"].write_text(report, encoding="utf-8")
    files["config"].write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    files["metrics"].write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    files["manifest"].write_text(
        json.dumps(dataset.manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _write_parquet(dataset.frame, files["dataset"])
    _write_parquet(pd.concat(static_predictions, ignore_index=True), files["predictions"])
    _write_parquet(walk_forward.predictions, files["walk_forward"])
    walk_forward.windows.to_csv(files["walk_forward_windows"], index=False)
    joblib.dump(final_estimator, files["model"])
    prediction_metrics.to_csv(files["model_comparison"], index=False)
    test_metrics.to_csv(files["backtest_metrics"], index=False)
    annual_metrics.to_csv(files["annual_metrics"], index=False)
    bucket_diagnostics.to_csv(files["bucket_diagnostics"], index=False)
    selected_holdings.to_csv(files["holdings"], index=False)
    curves.to_csv(files["curves"], index=False)
    titles = _artifact_titles()
    return [(artifact_type, path, titles[artifact_type]) for artifact_type, path in files.items()]


def _artifact_paths(output_dir: Path) -> dict[str, Path]:
    return {
        "summary": output_dir / "report.md",
        "config": output_dir / "config.json",
        "metrics": output_dir / "metrics.json",
        "manifest": output_dir / "dataset_manifest.json",
        "dataset": output_dir / "dataset.parquet",
        "predictions": output_dir / "predictions.parquet",
        "walk_forward": output_dir / "walk_forward_predictions.parquet",
        "walk_forward_windows": output_dir / "walk_forward_windows.csv",
        "model": output_dir / "model.joblib",
        "model_comparison": output_dir / "model_comparison.csv",
        "backtest_metrics": output_dir / "backtest_metrics.csv",
        "annual_metrics": output_dir / "annual_metrics.csv",
        "bucket_diagnostics": output_dir / "bucket_diagnostics.csv",
        "holdings": output_dir / "holdings.csv",
        "curves": output_dir / "curves.csv",
    }


def _artifact_titles() -> dict[str, str]:
    return {
        "summary": "研究报告", "config": "冻结配置", "metrics": "晋级指标",
        "manifest": "数据集清单", "dataset": "训练数据集", "predictions": "固定模型预测",
        "walk_forward": "Walk Forward 预测", "walk_forward_windows": "Walk Forward 窗口",
        "model": "研究模型", "model_comparison": "模型比较", "backtest_metrics": "M0 回测指标",
        "annual_metrics": "年度指标", "bucket_diagnostics": "预测分桶", "holdings": "Top20 持仓",
        "curves": "净值曲线",
    }


def _write_parquet(frame: pd.DataFrame, path: Path) -> None:
    connection = duckdb.connect(":memory:")
    try:
        connection.register("artifact_frame", frame)
        escaped = str(path.resolve()).replace("'", "''")
        connection.execute(f"COPY artifact_frame TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    finally:
        connection.close()
