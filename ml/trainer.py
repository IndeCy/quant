"""固定候选模型训练与横截面预测。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import RegressorMixin

from ml.models import ModelDefinition, fixed_model_definitions
from ml.preprocessing import MODEL_FEATURES, build_cross_section_features, monthly_equal_sample_weights
from ml.split import DatasetSplits


@dataclass(frozen=True)
class TrainedModel:
    """模型对象和三个区间的可审计预测。"""

    model_id: str
    model_name: str
    estimator: RegressorMixin
    predictions: pd.DataFrame
    metrics: dict[str, float]


def train_fixed_candidates(splits: DatasetSplits) -> dict[str, TrainedModel]:
    """只在训练集拟合两个冻结模型，并输出所有区间预测。"""
    prepared = {
        "train": build_cross_section_features(splits.train),
        "validation": build_cross_section_features(splits.validation),
        "test": build_cross_section_features(splits.test),
    }
    results: dict[str, TrainedModel] = {}
    for definition in fixed_model_definitions():
        estimator = fit_fixed_model(definition, prepared["train"])
        predictions = _predict_all_samples(estimator, prepared)
        metrics = summarize_prediction_metrics(predictions)
        results[definition.model_id] = TrainedModel(
            model_id=definition.model_id,
            model_name=definition.name,
            estimator=estimator,
            predictions=predictions,
            metrics=metrics,
        )
    return results


def fit_fixed_model(
    definition: ModelDefinition,
    train_frame: pd.DataFrame,
) -> RegressorMixin:
    """仅使用给定训练样本拟合一个冻结模型。"""
    prepared = build_cross_section_features(train_frame)
    train = prepared.dropna(subset=[*MODEL_FEATURES, "forward_rank"])
    if train.empty:
        raise ValueError("model training frame is empty")
    weights = monthly_equal_sample_weights(train)
    estimator = definition.builder()
    estimator.fit(
        train[list(MODEL_FEATURES)],
        train["forward_rank"].astype(float),
        **{definition.sample_weight_parameter: weights.to_numpy()},
    )
    return estimator


def predict_with_model(
    estimator: RegressorMixin,
    frame: pd.DataFrame,
    *,
    sample: str,
) -> pd.DataFrame:
    """对一个时段产生横截面预测和预测分位。"""
    prepared = build_cross_section_features(frame)
    valid = prepared.dropna(subset=list(MODEL_FEATURES)).copy()
    valid["prediction"] = np.asarray(estimator.predict(valid[list(MODEL_FEATURES)]), dtype=float)
    valid["prediction_rank"] = valid.groupby("signal_date")["prediction"].rank(
        pct=True,
        method="average",
    )
    valid["sample"] = sample
    columns = [
        "sample", "signal_date", "symbol", "prediction", "prediction_rank",
        "forward_return", "forward_rank", "entry_date", "exit_date",
    ]
    return valid[[column for column in columns if column in valid.columns]].reset_index(drop=True)


def summarize_prediction_metrics(predictions: pd.DataFrame) -> dict[str, float]:
    """按样本区间汇总月度 RankIC、ICIR 和正 IC 月比例。"""
    result: dict[str, float] = {}
    for sample, group in predictions.groupby("sample", sort=False):
        monthly_ic = pd.Series(
            {
                str(signal_date): values["prediction"].corr(values["forward_rank"], method="spearman")
                for signal_date, values in group.groupby("signal_date", sort=True)
            },
            dtype=float,
        ).dropna()
        mean_ic = float(monthly_ic.mean()) if not monthly_ic.empty else 0.0
        std_ic = float(monthly_ic.std(ddof=1)) if len(monthly_ic) > 1 else 0.0
        result[f"{sample}_mean_rank_ic"] = mean_ic
        result[f"{sample}_icir"] = mean_ic / std_ic if std_ic > 0 else 0.0
        result[f"{sample}_positive_ic_ratio"] = float(monthly_ic.gt(0).mean()) if not monthly_ic.empty else 0.0
        result[f"{sample}_month_count"] = float(len(monthly_ic))
    return result


def _predict_all_samples(
    estimator: RegressorMixin,
    prepared: dict[str, pd.DataFrame],
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for sample, frame in prepared.items():
        frames.append(predict_with_model(estimator, frame.dropna(subset=["forward_rank"]), sample=sample))
    return pd.concat(frames, ignore_index=True)
