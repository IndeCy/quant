"""固定 Ridge 横截面排序与年度扩展 Walk Forward。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from factors.quality import winsorize_series, zscore_series
from ml.preprocessing import monthly_equal_sample_weights


@dataclass(frozen=True)
class RidgeWalkForwardResult:
    """样本外预测、训练窗口、系数和最后一期模型。"""

    predictions: pd.DataFrame
    windows: pd.DataFrame
    coefficients: pd.DataFrame
    final_estimator: Pipeline


def build_cross_section_features(
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
) -> tuple[pd.DataFrame, tuple[str, ...]]:
    """每月独立1%/99%缩尾和标准化，不跨时间借用分布。"""
    missing = [
        column
        for column in ["signal_date", *feature_columns]
        if column not in frame.columns
    ]
    if missing:
        raise ValueError(f"ridge feature frame missing columns: {missing}")
    result = frame.copy()
    model_columns: list[str] = []
    for column in feature_columns:
        model_column = f"{column}_z"
        result[model_column] = result.groupby(
            "signal_date",
            group_keys=False,
        )[column].transform(
            lambda values: zscore_series(
                winsorize_series(values, lower=0.01, upper=0.99)
            )
        )
        model_columns.append(model_column)
    return result, tuple(model_columns)


def fit_fixed_ridge(
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
) -> Pipeline:
    """固定 alpha=1，不提供模型选择和参数搜索入口。"""
    prepared, model_columns = build_cross_section_features(
        frame,
        feature_columns,
    )
    train = prepared.dropna(
        subset=[*model_columns, "forward_rank"]
    ).copy()
    if train.empty:
        raise ValueError("ridge training frame is empty")
    weights = monthly_equal_sample_weights(train)
    estimator = Pipeline(
        [
            ("scale", StandardScaler()),
            ("ridge", Ridge(alpha=1.0)),
        ]
    )
    estimator.fit(
        train[list(model_columns)],
        train["forward_rank"].astype(float),
        ridge__sample_weight=weights.to_numpy(),
    )
    return estimator


def predict_fixed_ridge(
    estimator: Pipeline,
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
) -> pd.DataFrame:
    """对给定月份产生连续预测分数。"""
    prepared, model_columns = build_cross_section_features(
        frame,
        feature_columns,
    )
    valid = prepared.dropna(subset=list(model_columns)).copy()
    valid["prediction"] = np.asarray(
        estimator.predict(valid[list(model_columns)]),
        dtype=float,
    )
    valid["prediction_rank"] = valid.groupby(
        "signal_date"
    )["prediction"].rank(pct=True, method="average")
    columns = [
        "signal_date",
        "symbol",
        "prediction",
        "prediction_rank",
        "forward_return",
        "forward_rank",
        "entry_date",
        "exit_date",
    ]
    return valid[
        [column for column in columns if column in valid.columns]
    ].reset_index(drop=True)


def run_annual_expanding_ridge(
    frame: pd.DataFrame,
    feature_columns: tuple[str, ...],
    *,
    first_test_year: int,
) -> RidgeWalkForwardResult:
    """每年仅使用测试年以前已经结束的标签训练固定模型。"""
    data = frame.dropna(subset=["forward_rank", "exit_date"]).copy()
    years = sorted(
        year
        for year in data["signal_date"].astype(str).str[:4].astype(int).unique()
        if year >= first_test_year
    )
    predictions: list[pd.DataFrame] = []
    windows: list[dict[str, object]] = []
    coefficients: list[dict[str, object]] = []
    last_estimator: Pipeline | None = None
    for year in years:
        year_start = f"{year}0101"
        year_end = f"{year}1231"
        train = data[data["exit_date"].astype(str).lt(year_start)].copy()
        test = data[
            data["signal_date"].astype(str).between(
                year_start,
                year_end,
                inclusive="both",
            )
        ].copy()
        if train.empty or test.empty:
            continue
        estimator = fit_fixed_ridge(train, feature_columns)
        predicted = predict_fixed_ridge(estimator, test, feature_columns)
        predicted["test_year"] = year
        predictions.append(predicted)
        windows.append(
            {
                "test_year": year,
                "train_signal_start": str(train["signal_date"].min()),
                "train_signal_end": str(train["signal_date"].max()),
                "train_max_exit_date": str(train["exit_date"].max()),
                "test_signal_start": str(test["signal_date"].min()),
                "test_signal_end": str(test["signal_date"].max()),
                "train_rows": len(train),
                "test_rows": len(test),
            }
        )
        ridge = estimator.named_steps["ridge"]
        for feature, coefficient in zip(feature_columns, ridge.coef_):
            coefficients.append(
                {
                    "test_year": year,
                    "feature": feature,
                    "coefficient": float(coefficient),
                }
            )
        last_estimator = estimator
    if not predictions or last_estimator is None:
        raise ValueError("ridge walk-forward produced no predictions")
    window_frame = pd.DataFrame(windows)
    if (
        window_frame["train_max_exit_date"].astype(str)
        >= window_frame["test_signal_start"].astype(str)
    ).any():
        raise ValueError("walk-forward training labels overlap test signals")
    return RidgeWalkForwardResult(
        pd.concat(predictions, ignore_index=True),
        window_frame,
        pd.DataFrame(coefficients),
        last_estimator,
    )
